"""Admin authentication.

Passwords are stored as scrypt hashes with a per-user salt. Sessions are
HMAC-signed opaque tokens in an HttpOnly cookie rather than server-side state,
so they survive a restart and need no session table.

The signing key lives in server/data/session.key with 0600 permissions. If that
file is ever lost, every session invalidates and admins log in again, which is
the correct failure mode.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from pathlib import Path

from . import db

SESSION_COOKIE = "fixmate_admin"
CSRF_HEADER = "X-FixMate-CSRF"


def load_or_create_key(path: str | Path) -> bytes:
    key_path = Path(path)
    if key_path.is_file():
        data = key_path.read_bytes().strip()
        if len(data) >= 32:
            return data
    key = base64.urlsafe_b64encode(secrets.token_bytes(48))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def _sign(payload: str, key: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(key, payload.encode("utf-8"), sha256).digest()
    ).decode("ascii").rstrip("=")


class Sessions:
    def __init__(self, key: bytes, ttl_hours: int):
        self.key = key
        self.ttl_seconds = ttl_hours * 3600

    def issue(self, username: str) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(24)
        claims = {
            "sub": username,
            "csrf": csrf,
            "iat": int(time.time()),
            "exp": int(time.time()) + self.ttl_seconds,
            "jti": secrets.token_hex(8),
        }
        payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return f"{payload}.{_sign(payload, self.key)}", csrf

    def read(self, token: str | None) -> dict | None:
        if not token or "." not in token:
            return None
        payload, _, signature = token.rpartition(".")
        expected = _sign(payload, self.key)
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            padded = payload + "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(claims, dict):
            return None
        if int(claims.get("exp", 0)) < int(time.time()):
            return None
        return claims

    def cookie_header(self, token: str, max_age: int, secure: bool) -> str:
        parts = [
            f"{SESSION_COOKIE}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={max_age}",
        ]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_header(self, secure: bool) -> str:
        parts = [f"{SESSION_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=0"]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)


def authenticate(conn, username: str, password: str) -> bool:
    row = db.get_admin(conn, username.strip())
    if row is None:
        # Constant-ish work whether or not the user exists.
        db.verify_password(password, db.hash_password("decoy", b"\x00" * 16))
        return False
    return db.verify_password(password, row["password_hash"])


__all__ = [
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "Sessions",
    "authenticate",
    "load_or_create_key",
]