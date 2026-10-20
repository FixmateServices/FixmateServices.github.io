"""HTTP layer: public booking API, admin API, static files.

Standard library only. ThreadingHTTPServer is appropriate here because load is
small and every write is a sub-millisecond SQLite transaction; the database,
not the web server, is the concurrency control. The thread-per-request model
also means a slow n8n webhook can never block another customer's booking.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import sqlite3
import threading
import time
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import admin, db, notify
from .availability import REASON_TEXT, describe_range, slots_for_date
from .booking import CONFLICT_MESSAGE, BookingClosed, BookingConflict, create_booking
from .config import Config
from .tz import add_days, format_for_customer, now_utc, today_in
from .validate import ValidationError, validate_booking

LOG = logging.getLogger("fixmate")

MAX_BODY_BYTES = 32 * 1024
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8

PUBLIC_CACHE_CONTROL = "no-store"

SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
)

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class RateLimiter:
    """Fixed-window limiter keyed by client IP. In-memory by design."""

    def __init__(self, window_seconds: int, max_attempts: int):
        self.window = window_seconds
        self.max_attempts = max_attempts
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(bucket) >= self.max_attempts:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            if len(self._hits) > 2048:
                stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
                for k in stale:
                    self._hits.pop(k, None)
            return True


class App:
    def __init__(
        self,
        config: Config,
        db_path: str | Path,
        static_root: Path,
        session_key_path: Path,
    ):
        self.config = config
        self.db_path = Path(db_path)
        self.static_root = static_root
        self._local = threading.local()
        self.sessions = admin.Sessions(
            admin.load_or_create_key(session_key_path),
            config.admin_session_ttl_hours,
        )
        self.login_limiter = RateLimiter(LOGIN_WINDOW_SECONDS, LOGIN_MAX_ATTEMPTS)
        self.booking_limiter = RateLimiter(60, 12)
        db.init_db(self.conn())

    def conn(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is None:
            existing = db.connect(self.db_path)
            self._local.conn = existing
        return existing

    def close(self) -> None:
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            existing.close()
            self._local.conn = None

    def has_admin_user(self) -> bool:
        return db.count_admin(self.conn()) > 0

    # -- public ------------------------------------------------------------

    def public_config(self) -> dict:
        c = self.config
        return {
            "timezone": c.timezone_name,
            "locale": c.locale,
            "duration_minutes": c.appointment_duration_minutes,
            "granularity_minutes": c.slot_granularity_minutes,
            "min_notice_hours": c.min_notice_hours,
            "max_advance_days": c.max_advance_days,
            "horizon_days": c.booking_horizon_days,
            "show_booked_slots": c.show_booked_slots,
            "service_types": list(c.service_types),
            "today": today_in(c.zone).isoformat(),
            "busy_statuses": list(c.busy_statuses),
        }

    def availability_payload(self, day_iso: str) -> tuple[int, dict]:
        try:
            day = date.fromisoformat(day_iso)
        except ValueError:
            return 400, {"error": "invalid_date", "message": "Use YYYY-MM-DD"}

        today = today_in(self.config.zone)
        if day < today:
            return 400, {"error": "past_date", "message": "That date has passed"}
        if day > add_days(today, self.config.max_advance_days):
            return 400, {
                "error": "too_far",
                "message": f"We only take bookings up to {self.config.max_advance_days} days ahead",
            }

        slots = slots_for_date(self.conn(), self.config, day)
        return 200, {
            "date": day.isoformat(),
            "timezone": self.config.timezone_name,
            "duration_minutes": self.config.appointment_duration_minutes,
            "closed": day.isoformat() in self.config.holidays
            or day.isoformat() in self.config.closures,
            "slots": [
                {
                    "time": s.local_time,
                    "available": s.available,
                    "reason": s.reason,
                }
                for s in slots
            ],
            "available_count": len([s for s in slots if s.available]),
        }

    def month_payload(self, year: int, month: int) -> tuple[int, dict]:
        if month < 1 or month > 12:
            return 400, {"error": "invalid_month"}
        first = date(year, month, 1)
        last = add_days(
            date(year + (month == 12), 1 if month == 12 else month + 1, 1), -1
        )
        summary = describe_range(self.conn(), self.config, first, last)
        today = today_in(self.config.zone)
        return 200, {
            "year": year,
            "month": month,
            "first_weekday": first.weekday(),
            "days_in_month": last.day,
            "today": today.isoformat(),
            "days": summary,
            "timezone": self.config.timezone_name,
        }

    def create(self, payload: object, ip: str) -> tuple[int, dict]:
        request = validate_booking(payload, self.config.service_types)
        result = create_booking(self.conn(), self.config, request)
        notify.notify_async(self.new_connection, self.config, result.booking_id, LOG.warning)
        return 201, {
            "ok": True,
            "reference": result.reference,
            "status": result.status,
            "requested_date": result.local_date,
            "requested_time": result.local_time,
            "starts_at_utc": result.starts_at_utc,
            "utc_offset_minutes": result.utc_offset_minutes,
            "timezone": self.config.timezone_name,
            "message": (
                f"Your visit is requested for {result.customer_line}. "
                "We will confirm by phone or email."
            ),
        }

    def new_connection(self) -> sqlite3.Connection:
        """A connection for background work, separate from the request thread's."""
        return db.connect(self.db_path)

    # -- admin -------------------------------------------------------------

    def current_session(self, token: str | None) -> dict | None:
        return self.sessions.read(token)

    def login(
        self, username: str, password: str, secure: bool, ip: str
    ) -> tuple[int, dict, str | None]:
        # Keyed by IP *and* username: keyed by username alone, anyone could lock
        # the real admin out for 15 minutes by guessing their name.
        if not self.login_limiter.allow(f"login:{ip}:{username[:64]}"):
            return 429, {
                "error": "too_many_attempts",
                "message": "Too many sign-in attempts. Wait 15 minutes and try again.",
            }, None
        if not admin.authenticate(self.conn(), username, password):
            LOG.warning("failed admin login for %r from %s", username, ip)
            return 401, {"error": "invalid_credentials", "message": "Wrong username or password"}, None
        token, csrf = self.sessions.issue(username)
        cookie = self.sessions.cookie_header(token, self.config.admin_session_ttl_hours * 3600, secure)
        return 200, {"ok": True, "csrf": csrf, "username": username}, cookie

    def admin_list(self, session: dict, query: dict) -> tuple[int, dict]:
        status = (query.get("status") or [None])[0]
        if status and status not in {"Pending", "Confirmed", "Cancelled"}:
            return 400, {"error": "invalid_status"}
        try:
            limit = max(1, min(1000, int((query.get("limit") or ["200"])[0])))
        except ValueError:
            limit = 200
        rows = db.list_bookings(
            self.conn(),
            status=status,
            from_date=(query.get("from") or [None])[0],
            to_date=(query.get("to") or [None])[0],
            limit=limit,
        )
        return 200, {"bookings": [_admin_view(r) for r in rows]}

    def admin_set_status(
        self, session: dict, booking_id: str, new_status: str, note: str
    ) -> tuple[int, dict]:
        if new_status not in {"Pending", "Confirmed", "Cancelled"}:
            return 400, {"error": "invalid_status"}
        ok, detail = db.set_status(
            self.conn(), booking_id, new_status, session.get("sub", "admin"), note[:500]
        )
        if not ok:
            code = 404 if detail == "not_found" else 409
            return code, {
                "error": detail,
                "message": "Could not change that booking. Refresh and try again.",
            }
        row = db.get_booking(self.conn(), booking_id)
        notify.notify_async(self.new_connection, self.config, booking_id, LOG.warning)
        return 200, {"ok": True, "booking": _admin_view(row)}

    def admin_config_view(self) -> dict:
        c = self.config
        return {
            "timezone": c.timezone_name,
            "appointment_duration_minutes": c.appointment_duration_minutes,
            "slot_granularity_minutes": c.slot_granularity_minutes,
            "buffer_before_minutes": c.buffer_before_minutes,
            "buffer_after_minutes": c.buffer_after_minutes,
            "min_notice_hours": c.min_notice_hours,
            "max_advance_days": c.max_advance_days,
            "booking_horizon_days": c.booking_horizon_days,
            "busy_statuses": list(c.busy_statuses),
            "show_booked_slots": c.show_booked_slots,
            "holidays": sorted(c.holidays),
            "closures": sorted(c.closures),
            "working_hours": {
                k: [[w.start, w.end] for w in v] for k, v in c.working_hours.items()
            },
            "service_types": list(c.service_types),
            "notify_enabled": c.notify_enabled,
            "notify_configured": bool(
                c.notify_enabled and os.environ.get(c.notify_webhook_env, "").strip()
            ),
            "accepting_bookings": today_in(c.zone).isoformat() >= c.opening_closed_until,
            "opening_closed_until": c.opening_closed_until,
        }


def _admin_view(row: sqlite3.Row | None) -> dict:
    if row is None:
        return {}
    offset = int(row["utc_offset_minutes"] or 0)
    return {
        "id": row["id"],
        "reference": row["reference"],
        "status": row["status"],
        "requested_date": row["local_date"],
        "requested_time": row["local_time"],
        "summary": format_for_customer(row["local_date"], row["local_time"], offset),
        "utc_offset_minutes": offset,
        "full_name": row["full_name"],
        "phone": row["phone"],
        "email": row["email"],
        "service_type": row["service_type"],
        "property_address": row["property_address"],
        "postcode": row["postcode"],
        "job_description": row["job_description"],
        "admin_note": row["admin_note"],
        "duration_minutes": row["duration_minutes"],
        "created_at_utc": row["created_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
        "notified": row["notified_at_utc"] is not None,
    }


ROUTES: list[tuple[str, re.Pattern[str]]] = []


def route(method: str, pattern: str):
    compiled = re.compile(f"^{pattern}$")

    def decorate(fn):
        ROUTES.append((method, compiled, fn))
        return fn

    return decorate


def build_handler(app: App, secure_cookies: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FixMate"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # noqa: A003
            LOG.info("%s %s", self.address_string(), fmt % args)

        # -- helpers ---------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in SECURITY_HEADERS:
                self.send_header(key, value)
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict, extra=None):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers = {"Cache-Control": PUBLIC_CACHE_CONTROL}
            if extra:
                headers.update(extra)
            self._send(status, body, "application/json; charset=utf-8", headers)

        def _cookie_token(self) -> str | None:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            jar = SimpleCookie()
            try:
                jar.load(raw)
            except Exception:
                return None
            morsel = jar.get(admin.SESSION_COOKIE)
            return morsel.value if morsel else None

        def _require_session(self) -> dict | None:
            return app.current_session(self._cookie_token())

        def _require_admin_write(self, session: dict | None) -> bool:
            if session is None:
                return False
            return hmac_compare(
                self.headers.get(admin.CSRF_HEADER, ""), session.get("csrf", "")
            )

        def _body(self) -> tuple[object, int | None]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None, 400
            if length <= 0:
                return None, 400
            if length > MAX_BODY_BYTES:
                return None, 413
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8")), None
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, 400

        def _client_key(self) -> str:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return self.client_address[0] if self.client_address else "unknown"

        # -- routing ---------------------------------------------------

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method: str):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            try:
                for route_method, pattern, handler in ROUTES:
                    if route_method != method:
                        continue
                    match = pattern.match(path)
                    if not match:
                        continue
                    handler(self, app, match, query)
                    return
                if method == "GET":
                    self._serve_static(path)
                    return
                self._json(404, {"error": "not_found"})
            except ValidationError as exc:
                self._json(400, exc.as_dict())
            except BookingConflict as exc:
                self._json(
                    exc.status_code,
                    {
                        "error": "slot_unavailable",
                        "reason": exc.reason,
                        "message": exc.message,
                        "recheck_required": True,
                    },
                )
            except BookingClosed as exc:
                self._json(exc.status_code, {"error": "booking_closed", "message": exc.message})
            except sqlite3.OperationalError as exc:
                LOG.exception("database error")
                self._json(503, {"error": "temporarily_unavailable",
                                 "message": "Please try again in a moment."})
                del exc
            except BrokenPipeError:
                pass
            except Exception:
                LOG.exception("unhandled error on %s %s", method, path)
                self._json(500, {"error": "server_error"})

        # -- static ----------------------------------------------------

        def _serve_static(self, path: str):
            root = app.static_root.resolve()
            relative = path.lstrip("/") or "index.html"
            if relative.endswith("/"):
                relative += "index.html"
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                self._json(403, {"error": "forbidden"})
                return
            if not target.is_file():
                self._json(404, {"error": "not_found"})
                return

            suffix = target.suffix.lower()
            content_type = _STATIC_TYPES.get(suffix) or (
                mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            )
            body = target.read_bytes()
            cache = "no-cache" if suffix in {".html", ".css", ".js"} else "public, max-age=86400"
            self._send(200, body, content_type, {"Cache-Control": cache})

    return Handler


def hmac_compare(a: str, b: str) -> bool:
    import hmac as _hmac

    return bool(a) and bool(b) and _hmac.compare_digest(a, b)


@route("GET", r"/api/health")
def _health(h, app, match, query):
    h._json(200, {"ok": True, "time_utc": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")})


@route("GET", r"/api/booking/config")
def _config(h, app, match, query):
    h._json(200, app.public_config())


@route("GET", r"/api/booking/availability")
def _availability(h, app, match, query):
    day = (query.get("date") or [""])[0]
    status, payload = app.availability_payload(day)
    h._json(status, payload)


@route("GET", r"/api/booking/month")
def _month(h, app, match, query):
    today = today_in(app.config.zone)
    try:
        year = int((query.get("year") or [str(today.year)])[0])
        month = int((query.get("month") or [str(today.month)])[0])
    except ValueError:
        h._json(400, {"error": "invalid_month"})
        return
    status, payload = app.month_payload(year, month)
    h._json(status, payload)


@route("POST", r"/api/booking")
def _create(h, app, match, query):
    if not app.booking_limiter.allow(f"book:{h._client_key()}"):
        h._json(429, {"error": "rate_limited",
                      "message": "Too many attempts. Please wait a minute or call us."})
        return
    payload, error = h._body()
    if error is not None:
        h._json(error, {"error": "invalid_body"})
        return
    status, result = app.create(payload, h._client_key())
    h._json(status, result)


@route("POST", r"/api/admin/login")
def _login(h, app, match, query):
    payload, error = h._body()
    if error is not None or not isinstance(payload, dict):
        h._json(400, {"error": "invalid_body"})
        return
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if not username or not password or len(password) > 200:
        h._json(401, {"error": "invalid_credentials", "message": "Wrong username or password"})
        return
    status, result, cookie = app.login(username, password, secure_cookies, h._client_key())
    extra = {"Set-Cookie": cookie} if cookie else None
    h._json(status, result, extra)


@route("POST", r"/api/admin/logout")
def _logout(h, app, match, query):
    h._json(200, {"ok": True}, {"Set-Cookie": app.sessions.clear_header(secure_cookies)})


@route("GET", r"/api/admin/session")
def _session(h, app, match, query):
    session = h._require_session()
    if session is None:
        h._json(401, {"error": "unauthenticated"})
        return
    h._json(200, {"ok": True, "username": session.get("sub"), "csrf": session.get("csrf")})


@route("GET", r"/api/admin/bookings")
def _list(h, app, match, query):
    session = h._require_session()
    if session is None:
        h._json(401, {"error": "unauthenticated"})
        return
    status, payload = app.admin_list(session, query)
    h._json(status, payload)


@route("GET", r"/api/admin/settings")
def _settings(h, app, match, query):
    if h._require_session() is None:
        h._json(401, {"error": "unauthenticated"})
        return
    h._json(200, app.admin_config_view())


@route("POST", r"/api/admin/bookings/(?P<booking_id>[A-Za-z0-9_-]{6,64})/status")
def _set_status(h, app, match, query):
    session = h._require_session()
    if session is None:
        h._json(401, {"error": "unauthenticated"})
        return
    if not h._require_admin_write(session):
        h._json(403, {"error": "csrf_failed"})
        return
    payload, error = h._body()
    if error is not None or not isinstance(payload, dict):
        h._json(400, {"error": "invalid_body"})
        return
    status, result = app.admin_set_status(
        session,
        match.group("booking_id"),
        str(payload.get("status", "")),
        str(payload.get("note", "")),
    )
    h._json(status, result)


def serve(app: App, host: str, port: int, secure_cookies: bool) -> None:
    handler = build_handler(app, secure_cookies)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    LOG.info("FixMate booking server on http://%s:%s", host, port)
    LOG.info("booking open: %s", app.admin_config_view()["accepting_bookings"])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        httpd.server_close()


__all__ = ["App", "ROUTES", "RateLimiter", "build_handler", "route", "serve"]