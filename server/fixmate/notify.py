"""Google Sheets copy via n8n.

This is strictly downstream of the database write. The booking is already saved
and already occupies the slot before this module runs, so a failure here can
never cause a double booking or a lost booking. Google Sheets is a report and a
convenience, never the source of availability.

The webhook URL and shared secret come from the environment, never from
config.json or any file the browser can read. Each payload is signed with
HMAC-SHA256 so n8n can reject anything that did not come from this server.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db
from .config import Config
from .tz import format_for_customer


def _sign(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_payload(conn: sqlite3.Connection, booking_id: str) -> dict | None:
    row = db.get_booking(conn, booking_id)
    if row is None:
        return None

    start = datetime.strptime(row["starts_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    try:
        offset = int(row["utc_offset_minutes"])
    except (TypeError, ValueError):
        offset = 0
    suffix = "GMT" if offset == 0 else "BST"

    return {
        "booking_id": row["id"],
        "reference": row["reference"],
        "status": row["status"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "email": row["email"],
        "service_type": row["service_type"],
        "property_address": row["property_address"],
        "postcode": row["postcode"],
        "job_description": row["job_description"],
        "requested_date": row["local_date"],
        "requested_time": row["local_time"],
        "starts_at_utc": row["starts_at_utc"],
        "ends_at_utc": row["ends_at_utc"],
        "utc_offset_minutes": offset,
        "customer_summary": format_for_customer(
            row["local_date"], row["local_time"], offset
        ),
        "timezone": "Europe/London",
        "timezone_suffix": suffix,
        "duration_minutes": row["duration_minutes"],
        "source": "fixmate-website",
        "created_at_utc": row["created_at_utc"],
    }


def _deliver(url: str, secret: str, payload: dict, timeout: int) -> tuple[bool, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-FixMate-Signature": _sign(body, secret),
            "User-Agent": "FixMateBooking/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = getattr(response, "status", response.getcode())
            return 200 <= int(code) < 300, f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"network: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - notification must never crash a booking
        return False, f"error: {exc}"


def notify_async(
    conn_factory,
    config: Config,
    booking_id: str,
    log,
) -> None:
    """Fire the notification without blocking the customer's response."""
    if not config.notify_enabled:
        return

    url = os.environ.get(config.notify_webhook_env, "").strip()
    if not url:
        log("notify skipped: %s not set", config.notify_webhook_env)
        return

    secret = os.environ.get(config.notify_secret_env, "").strip()
    if not secret:
        log("notify skipped: %s not set", config.notify_secret_env)
        return

    def worker() -> None:
        conn = conn_factory()
        try:
            payload = build_payload(conn, booking_id)
            if payload is None:
                return
            ok, detail = _deliver(url, secret, payload, config.notify_timeout_seconds)
            if ok:
                db.mark_notified(conn, booking_id)
                log("notified %s -> ok", payload["reference"])
            else:
                log("notified %s -> FAILED (%s); will retry", payload["reference"], detail)
        except Exception as exc:  # noqa: BLE001
            log("notify error for %s: %s", booking_id, exc)
        finally:
            conn.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def retry_pending(conn_factory, config: Config, log) -> int:
    """Send anything that never made it. Called on server start."""
    if not config.notify_enabled:
        return 0
    url = os.environ.get(config.notify_webhook_env, "").strip()
    secret = os.environ.get(config.notify_secret_env, "").strip()
    if not url or not secret:
        return 0

    conn = conn_factory()
    sent = 0
    try:
        rows = db.unnotified(conn)
        for row in rows:
            payload = build_payload(conn, row["id"])
            if payload is None:
                continue
            ok, detail = _deliver(url, secret, payload, config.notify_timeout_seconds)
            if ok:
                db.mark_notified(conn, row["id"])
                sent += 1
            else:
                log("retry failed for %s (%s)", row["reference"], detail)
    finally:
        conn.close()
    return sent


__all__ = ["build_payload", "notify_async", "retry_pending"]