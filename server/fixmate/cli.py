"""Command line entry point.

    python3 -m fixmate.cli serve      --port 8080
    python3 -m fixmate.cli init-admin --password "..."
    python3 -m fixmate.cli show-config
    python3 -m fixmate.cli self-test
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path

from . import admin, db, notify
from .booking import BookingClosed
from .config import ConfigError, load_config
from .http_app import App, serve

HERE = Path(__file__).resolve().parent
SERVER_ROOT = HERE.parent
PROJECT_ROOT = SERVER_ROOT.parent

DEFAULT_CONFIG = SERVER_ROOT / "config.json"
DEFAULT_DB = SERVER_ROOT / "data" / "bookings.db"
DEFAULT_STATIC = PROJECT_ROOT
DEFAULT_KEY = SERVER_ROOT / "data" / "session.key"


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _app(args) -> App:
    config = load_config(getattr(args, "config", None) or DEFAULT_CONFIG)
    db_path = getattr(args, "db", None) or DEFAULT_DB
    static_root = Path(getattr(args, "static", None) or DEFAULT_STATIC).resolve()
    key_path = DEFAULT_KEY
    return App(config, db_path, static_root, key_path)


def cmd_serve(args) -> int:
    log = logging.getLogger("fixmate")
    app = _app(args)
    host = args.host
    port = args.port
    secure = args.secure_cookies or os.environ.get("FIXMATE_SECURE_COOKIES") == "1"
    if not args.secure_cookies:
        log.warning(
            "Running without --secure-cookies. Use HTTPS in production so the "
            "admin session cookie is never sent in clear text."
        )

    if app.config.notify_enabled:
        resent = notify.retry_pending(app.new_connection, app.config, log.warning)
        if resent:
            log.info("re-sent %d unsent booking(s) to n8n", resent)

    if not app.has_admin_user():
        log.warning(
            "no admin account exists yet. Run: python3 -m fixmate.cli init-admin"
        )

    serve(app, host, port, secure)
    return 0


def cmd_init_admin(args) -> int:
    config = load_config(getattr(args, "config", None) or DEFAULT_CONFIG)
    db_path = getattr(args, "db", None) or DEFAULT_DB
    conn = db.connect(db_path)
    db.init_db(conn)
    username = args.username or config.admin_username

    if db.count_admin(conn) and not args.force:
        print(
            "An admin account already exists. Re-running replaces its password.\n"
            "Use --force to confirm you want that."
        )
        return 1

    if args.password:
        password = args.password
    else:
        try:
            password = getpass.getpass(f"Password for {username}: ")
            confirm = getpass.getpass("Confirm: ")
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled")
            return 1

    if len(password) < 12:
        print("Password must be at least 12 characters.")
        return 1

    result = db.upsert_admin(conn, username, password, rotate=args.force)
    print(f"admin '{username}' {result}")
    print(f"database: {db_path}")
    print("Sign in at /admin.html")
    conn.close()
    return 0


def cmd_show_config(args) -> int:
    config = load_config(getattr(args, "config", None) or DEFAULT_CONFIG)
    view = {
        "timezone": config.timezone_name,
        "duration_minutes": config.appointment_duration_minutes,
        "granularity_minutes": config.slot_granularity_minutes,
        "buffers": [config.buffer_before_minutes, config.buffer_after_minutes],
        "min_notice_hours": config.min_notice_hours,
        "max_advance_days": config.max_advance_days,
        "horizon_days": config.booking_horizon_days,
        "busy_statuses": list(config.busy_statuses),
        "show_booked_slots": config.show_booked_slots,
        "holidays": sorted(config.holidays),
        "closures": sorted(config.closures),
        "working_hours": {
            k: [[w.start, w.end] for w in v] for k, v in config.working_hours.items()
        },
        "service_types": list(config.service_types),
        "opening_closed_until": config.opening_closed_until,
        "notify_enabled": config.notify_enabled,
        "notify_configured": bool(
            config.notify_enabled
            and os.environ.get(config.notify_webhook_env, "").strip()
            and os.environ.get(config.notify_secret_env, "").strip()
        ),
    }
    import json

    print(json.dumps(view, indent=2))
    if today_blocking(config):
        print(
            "\nBooking is CLOSED until "
            f"{config.opening_closed_until} (safety switch still set)."
        )
    return 0


def today_blocking(config) -> bool:
    from .config import is_accepting_bookings
    from .tz import today_in

    return not is_accepting_bookings(config, today_in(config.zone).isoformat())


def cmd_self_test(args) -> int:
    from .tests_selftest import run

    return run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixmate", description="FixMate booking server")
    parser.add_argument("--config", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--static", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the HTTP server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--secure-cookies", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_admin = sub.add_parser("init-admin", help="create or rotate the admin account")
    p_admin.add_argument("--username", default=None)
    p_admin.add_argument("--password", default=None)
    p_admin.add_argument("--force", action="store_true")
    p_admin.set_defaults(func=cmd_init_admin)

    p_show = sub.add_parser("show-config", help="print the effective settings")
    p_show.set_defaults(func=cmd_show_config)

    p_test = sub.add_parser("self-test", help="run the booking engine test suite")
    p_test.set_defaults(func=cmd_self_test)

    args = parser.parse_args(argv)
    _logging(args.verbose)

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except BookingClosed as exc:
        print(exc.message, file=sys.stderr)
        return 3


__all__ = ["main", "DEFAULT_CONFIG", "DEFAULT_DB", "DEFAULT_KEY", "DEFAULT_STATIC"]


if __name__ == "__main__":
    sys.exit(main())