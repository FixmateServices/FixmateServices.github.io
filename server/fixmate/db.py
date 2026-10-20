"""SQLite storage.

Availability and booking state live here, not in Google Sheets and not in the
browser. The browser can only ever hold a copy.

The important object in this file is ux_bookings_active_slot: a partial UNIQUE
index over (local_date, local_time) restricted to non-cancelled statuses. It is
the mechanism that makes double booking impossible. Two requests for 09:00 on the
same day race to INSERT; the database lets exactly one win and the other gets an
IntegrityError, regardless of application-level checking or timing.

notified_at_utc is deliberately NULL on insert. It is set only after n8n has
actually accepted the payload, so notified_at_utc IS NULL is a reliable "still
needs sending" queue. A column default would mark every booking as sent the
moment it was written and silently disable retries.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id                  TEXT PRIMARY KEY,
    reference           TEXT NOT NULL UNIQUE,
    status              TEXT NOT NULL
                        CHECK (status IN ('Pending', 'Confirmed', 'Cancelled')),
    local_date          TEXT NOT NULL,
    local_time          TEXT NOT NULL,
    utc_offset_minutes  INTEGER NOT NULL,
    starts_at_utc       TEXT NOT NULL,
    ends_at_utc         TEXT NOT NULL,
    duration_minutes    INTEGER NOT NULL,
    full_name           TEXT NOT NULL,
    phone               TEXT NOT NULL,
    email               TEXT NOT NULL,
    service_type        TEXT NOT NULL,
    property_address    TEXT NOT NULL,
    postcode            TEXT NOT NULL,
    job_description     TEXT NOT NULL,
    admin_note          TEXT NOT NULL DEFAULT '',
    created_at_utc      TEXT NOT NULL,
    updated_at_utc      TEXT NOT NULL,
    confirmed_at_utc    TEXT,
    cancelled_at_utc    TEXT,
    notified_at_utc     TEXT,
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_bookings_reference
    ON bookings (reference);

CREATE UNIQUE INDEX IF NOT EXISTS ux_bookings_active_slot
    ON bookings (local_date, local_time)
    WHERE status IN ('Pending', 'Confirmed');

CREATE INDEX IF NOT EXISTS ix_bookings_date
    ON bookings (local_date);

CREATE INDEX IF NOT EXISTS ix_bookings_status
    ON bookings (status);

CREATE TABLE IF NOT EXISTS booking_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id   TEXT NOT NULL REFERENCES bookings (id) ON DELETE CASCADE,
    from_status  TEXT,
    to_status    TEXT NOT NULL,
    actor        TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    at_utc       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_booking
    ON booking_events (booking_id, at_utc);

CREATE TABLE IF NOT EXISTS admin_users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    created_at_utc  TEXT NOT NULL,
    rotated_at_utc  TEXT
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return secrets.token_hex(16)


def new_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"FM-{body}"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite in a configuration that is safe for concurrent writers.

    WAL lets readers continue while a writer holds the lock, which matters
    because the availability endpoint is read constantly while bookings are
    being written. busy_timeout stops a second writer from failing instantly
    when it collides; it waits for the lock, then the UNIQUE index decides.
    """
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(db_path),
        timeout=15.0,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', ?)",
        (str(SCHEMA_VERSION),),
    )


def insert_booking(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    columns = ", ".join(record.keys())
    placeholders = ", ".join("?" for _ in record)
    conn.execute(
        f"INSERT INTO bookings ({columns}) VALUES ({placeholders})",
        tuple(record.values()),
    )


def add_event(
    conn: sqlite3.Connection,
    booking_id: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    note: str = "",
) -> None:
    conn.execute(
        "INSERT INTO booking_events "
        "(booking_id, from_status, to_status, actor, note, at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (booking_id, from_status, to_status, actor, note, utc_now_iso()),
    )


def get_booking(conn: sqlite3.Connection, booking_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM bookings WHERE id = ?", (booking_id,)
    ).fetchone()


def get_booking_by_reference(
    conn: sqlite3.Connection, reference: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM bookings WHERE reference = ?", (reference,)
    ).fetchone()


def busy_intervals_on(
    conn: sqlite3.Connection, local_date: str, busy_statuses: Iterable[str]
) -> list[sqlite3.Row]:
    statuses = list(busy_statuses)
    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM bookings WHERE local_date = ? "
        f"AND status IN ({placeholders})",
        (local_date, *statuses),
    ).fetchall()
    return rows


def busy_intervals_between(
    conn: sqlite3.Connection, start_date: str, end_date: str, busy_statuses: Iterable[str]
) -> list[sqlite3.Row]:
    statuses = list(busy_statuses)
    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM bookings WHERE local_date BETWEEN ? AND ? "
        f"AND status IN ({placeholders})",
        (start_date, end_date, *statuses),
    ).fetchall()
    return rows


def list_bookings(
    conn: sqlite3.Connection,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if from_date:
        clauses.append("local_date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("local_date <= ?")
        params.append(to_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM bookings {where} ORDER BY starts_at_utc ASC LIMIT ?",
        tuple(params),
    ).fetchall()


def events_for(conn: sqlite3.Connection, booking_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM booking_events WHERE booking_id = ? ORDER BY at_utc ASC",
        (booking_id,),
    ).fetchall()


def set_status(
    conn: sqlite3.Connection,
    booking_id: str,
    new_status: str,
    actor: str,
    note: str = "",
) -> tuple[bool, str]:
    """Move a booking between statuses.

    Uses a conditional UPDATE so two admins acting at once cannot both win, and
    relies on the partial UNIQUE index for the cancel-while-someone-books race.
    """
    current = get_booking(conn, booking_id)
    if current is None:
        return False, "not_found"
    if current["status"] == new_status:
        return False, "already_in_state"

    stamp = utc_now_iso()
    if new_status == "Confirmed":
        sql = (
            "UPDATE bookings SET status = ?, updated_at_utc = ?, "
            "confirmed_at_utc = ? WHERE id = ? AND status = 'Pending'"
        )
        params = (new_status, stamp, stamp, booking_id)
    elif new_status == "Cancelled":
        sql = (
            "UPDATE bookings SET status = ?, updated_at_utc = ?, "
            "cancelled_at_utc = ? WHERE id = ? AND status != 'Cancelled'"
        )
        params = (new_status, stamp, stamp, booking_id)
    else:
        sql = (
            "UPDATE bookings SET status = ?, updated_at_utc = ? "
            "WHERE id = ? AND status != 'Cancelled'"
        )
        params = (new_status, stamp, booking_id)

    cursor = conn.execute(sql, params)
    if cursor.rowcount == 0:
        return False, "conflict"
    add_event(conn, booking_id, current["status"], new_status, actor, note)
    return True, new_status.lower()


def mark_notified(conn: sqlite3.Connection, booking_id: str) -> None:
    conn.execute(
        "UPDATE bookings SET notified_at_utc = ? WHERE id = ?",
        (utc_now_iso(), booking_id),
    )


def unnotified(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bookings WHERE notified_at_utc IS NULL "
        "ORDER BY created_at_utc ASC LIMIT ?",
        (limit,),
    ).fetchall()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib_scrypt(password.encode("utf-8"), salt)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    import hmac

    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        expected = bytes.fromhex(digest_hex)
        actual = hashlib_scrypt(password.encode("utf-8"), bytes.fromhex(salt_hex))
    except ValueError:
        return False
    return hmac.compare_digest(expected, actual)


def hashlib_scrypt(password: bytes, salt: bytes) -> bytes:
    import hashlib

    return hashlib.scrypt(
        password, salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )


def upsert_admin(
    conn: sqlite3.Connection, username: str, password: str, rotate: bool = False
) -> str:
    existing = conn.execute(
        "SELECT username FROM admin_users WHERE username = ?", (username,)
    ).fetchone()
    stamp = utc_now_iso()
    stored = hash_password(password)
    if existing:
        conn.execute(
            "UPDATE admin_users SET password_hash = ?, rotated_at_utc = ? "
            "WHERE username = ?",
            (stored, stamp, username),
        )
        return "rotated"
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, created_at_utc) "
        "VALUES (?, ?, ?)",
        (username, stored, stamp),
    )
    return "created"


def get_admin(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM admin_users WHERE username = ?", (username,)
    ).fetchone()


def count_admin(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
    return int(row["n"])


__all__ = [
    "SCHEMA_VERSION",
    "add_event",
    "busy_intervals_between",
    "busy_intervals_on",
    "connect",
    "count_admin",
    "events_for",
    "get_admin",
    "get_booking",
    "get_booking_by_reference",
    "hash_password",
    "init_db",
    "insert_booking",
    "list_bookings",
    "mark_notified",
    "new_id",
    "new_reference",
    "set_status",
    "unnotified",
    "upsert_admin",
    "utc_now_iso",
    "verify_password",
]