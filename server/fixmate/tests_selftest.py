"""Dependency-free test suite.

Run with:  python3 -m fixmate.tests_selftest
or:        python3 -m fixmate.cli self-test

The concurrency tests are the important ones. test_concurrent_same_slot proves
that when many threads race for one time slot exactly one wins; test_cancel_then_
rebook proves a cancelled slot becomes available again.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import traceback
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import availability, db
from .booking import CONFLICT_MESSAGE, BookingConflict, create_booking
from .config import load_config
from .tz import wall_clock_to_utc

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))


def _tmp_config(tmp: Path, **overrides) -> Path:
    base = {
        "timezone": "Europe/London",
        "appointment_duration_minutes": 60,
        "slot_granularity_minutes": 30,
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0,
        "min_notice_hours": 0,
        "max_advance_days": 90,
        "booking_horizon_days": 90,
        "busy_statuses": ["Pending", "Confirmed"],
        "show_booked_slots": True,
        "holidays": ["2026-01-01"],
        "closures": ["2026-08-10"],
        "working_hours": {
            "mon": [["09:00", "17:00"]],
            "tue": [["09:00", "17:00"]],
            "wed": [["09:00", "17:00"]],
            "thu": [["09:00", "17:00"]],
            "fri": [["09:00", "17:00"]],
            "sat": [["10:00", "14:00"]],
            "sun": [],
        },
        "service_types": ["painting", "carpentry"],
        "opening_closed_until_YYYY_MM_DD": "2000-01-01",
        "admin": {"username": "admin"},
        "notify": {"enabled": False},
    }
    base.update(overrides)
    path = tmp / f"config-{abs(hash(json.dumps(base, sort_keys=True)))}.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


class FakeRequest:
    def __init__(self, day: date, clock: str, name: str = "Test User"):
        self.full_name = name
        self.phone = "07784044111"
        self.email = "test@example.com"
        self.service_type = "painting"
        self.property_address = "12 Example Street"
        self.postcode = "SW1A 1AA"
        self.job_description = "Test job"
        self.requested_date = day
        self.requested_time = clock


def _next_weekday(config, weekday_target: int, weeks_ahead: int = 2) -> date:
    """A date in the future that falls on the requested weekday index."""
    from .tz import today_in

    today = today_in(config.zone)
    cursor = today
    while cursor.weekday() != weekday_target:
        cursor += timedelta(days=1)
    return cursor + timedelta(weeks=weeks_ahead)


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


def test_availability_basics(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp))
    conn = db.connect(tmp / "a.db")
    db.init_db(conn)

    day = _next_weekday(config, 0)
    slots = availability.slots_for_date(conn, config, day)
    free = [s.local_time for s in slots if s.available]
    check(
        "availability: 09:00-16:00 start times for a 60min job in 09:00-17:00",
        free == [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)][:16],
        f"got {free}",
    )

    sunday = _next_weekday(config, 6)
    sunday_slots = availability.slots_for_date(conn, config, sunday)
    check("availability: Sunday closed returns no slots", not sunday_slots,
          f"{len(sunday_slots)} slots")

    saturday = _next_weekday(config, 5)
    sat_free = [s.local_time for s in availability.slots_for_date(conn, config, saturday)
                if s.available]
    check("availability: Saturday 10:00-14:00 window honoured",
          sat_free == ["10:00", "11:00", "12:00", "13:00"], f"got {sat_free}")

    conn.close()


def test_availability_holiday_and_closure(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp))
    conn = db.connect(tmp / "b.db")
    db.init_db(conn)

    holiday = date(2026, 1, 1)
    check("availability: holiday yields nothing",
          availability.slots_for_date(conn, config, holiday) == [])

    closed = date(2026, 8, 10)
    check("availability: closure yields nothing",
          availability.slots_for_date(conn, config, closed) == [])

    conn.close()


def test_buffer_windows(tmp: Path) -> None:
    """The grid and the booking re-check must agree about buffers.

    If they disagree the customer is offered a time that the save then refuses,
    which looks exactly like a double booking and destroys trust in the system.
    """
    config = load_config(
        _tmp_config(
            tmp,
            working_hours={"fri": [["09:00", "17:00"]]},
            buffer_before_minutes=30,
            buffer_after_minutes=45,
        )
    )
    conn = db.connect(tmp / "buffers.db")
    db.init_db(conn)
    day = _next_weekday(config, 4)

    free = [s.local_time for s in availability.slots_for_date(conn, config, day)
            if s.available]
    check("buffer: first slot starts after buffer_before",
          bool(free) and free[0] == "09:30", f"got {free[:1]}")
    check("buffer: last slot leaves buffer_after before closing",
          bool(free) and free[-1] == "15:00", f"got {free[-1:]}")

    ok, reason = availability.is_slot_available(conn, config, day, "09:00")
    check("buffer: re-check rejects the time the grid withheld",
          not ok and reason == "closed", f"{ok} {reason}")

    ok2, _ = availability.is_slot_available(conn, config, day, "09:30")
    check("buffer: re-check accepts the first slot the grid offered", ok2)

    ok3, reason3 = availability.is_slot_available(conn, config, day, "16:00")
    check("buffer: re-check rejects a job that cannot finish before closing",
          not ok3 and reason3 == "closed", f"{ok3} {reason3}")

    every_slot = availability.slots_for_date(conn, config, day)
    mismatched = [
        s.local_time for s in every_slot
        if s.available != availability.is_slot_available(conn, config, day, s.local_time)[0]
    ]
    check("buffer: grid and re-check agree on every slot of the day",
          not mismatched, f"disagree on {mismatched}")

    booking_ok = False
    try:
        create_booking(conn, config, FakeRequest(day, "09:00", "Too Early"))
        booking_ok = True
    except BookingConflict:
        pass
    check("buffer: booking a withheld time is refused", not booking_ok)

    accepted = create_booking(conn, config, FakeRequest(day, "09:30", "On Time"))
    check("buffer: booking the first offered time succeeds",
          accepted.local_time == "09:30")

    conn.close()


def test_availability_min_notice(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp, min_notice_hours=48))
    conn = db.connect(tmp / "c.db")
    db.init_db(conn)

    from .tz import today_in

    today = today_in(config.zone)
    now = datetime.now(timezone.utc)
    same_day = availability.slots_for_date(conn, config, today, now)
    check("availability: min notice blocks today",
          not any(s.available for s in same_day))

    far = today + timedelta(days=30)
    far_slots = availability.slots_for_date(conn, config, far, now)
    check("availability: min notice allows a date 30 days out",
          any(s.available for s in far_slots))

    conn.close()


def test_dst_transitions(tmp: Path) -> None:
    config = load_config(
        _tmp_config(
            tmp,
            working_hours={
                "mon": [["00:00", "23:59"]],
                "tue": [["00:00", "23:59"]],
                "wed": [["00:00", "23:59"]],
                "thu": [["00:00", "23:59"]],
                "fri": [["00:00", "23:59"]],
                "sat": [["00:00", "23:59"]],
                "sun": [["00:00", "23:59"]],
            },
            slot_granularity_minutes=30,
            appointment_duration_minutes=30,
        )
    )

    spring = date(2026, 3, 29)
    one_am = wall_clock_to_utc(spring, time(1, 30), config.zone)
    check("DST spring: 01:30 on 2026-03-29 does not exist", one_am is None,
          f"got {one_am}")

    autumn = date(2026, 10, 25)
    one_thirty = wall_clock_to_utc(autumn, time(1, 30), config.zone)
    check("DST autumn: 01:30 on 2026-10-25 resolves once", one_thirty is not None)

    normal = wall_clock_to_utc(date(2026, 6, 15), time(9, 0), config.zone)
    check("DST: ordinary summer time resolves to UTC+1",
          normal is not None and normal.hour == 8, f"got {normal}")

    winter = wall_clock_to_utc(date(2026, 1, 15), time(9, 0), config.zone)
    check("DST: ordinary winter time resolves to UTC+0",
          winter is not None and winter.hour == 9, f"got {winter}")


# --------------------------------------------------------------------------
# Booking + concurrency
# --------------------------------------------------------------------------


def test_booking_success_and_conflict(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp))
    conn = db.connect(tmp / "d.db")
    db.init_db(conn)

    day = _next_weekday(config, 2)
    result = create_booking(conn, config, FakeRequest(day, "10:00"))
    check("booking: first booking succeeds", result.reference.startswith("FM-"),
          result.reference)
    check("booking: starts Pending", result.status == "Pending")
    check("booking: local time stored", result.local_time == "10:00")

    try:
        create_booking(conn, config, FakeRequest(day, "10:00", "Second"))
        check("booking: duplicate slot rejected", False, "no exception raised")
    except BookingConflict as exc:
        check("booking: duplicate slot rejected", True)
        check("booking: conflict message is the required wording",
              exc.message == CONFLICT_MESSAGE, exc.message)

    other = create_booking(conn, config, FakeRequest(day, "14:00"))
    check("booking: a different slot on the same day still works",
          other.booking_id != result.booking_id)

    conn.close()


def test_cancel_frees_the_slot(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp))
    conn = db.connect(tmp / "e.db")
    db.init_db(conn)

    day = _next_weekday(config, 3)
    first = create_booking(conn, config, FakeRequest(day, "11:00"))

    ok, detail = db.set_status(conn, first.booking_id, "Cancelled", "admin", "test")
    check("cancel: status change succeeded", ok, detail)

    again = create_booking(conn, config, FakeRequest(day, "11:00", "Second"))
    check("cancel: the same slot can be booked again",
          again.booking_id != first.booking_id)

    ok2, _ = db.set_status(conn, first.booking_id, "Confirmed", "admin")
    check("cancel: cannot resurrect a cancelled booking", not ok2)

    conn.close()


def test_concurrent_same_slot(tmp: Path) -> None:
    """The headline guarantee: one slot, many simultaneous requests, one winner."""
    config = load_config(_tmp_config(tmp))
    db_path = tmp / "race.db"
    setup = db.connect(db_path)
    db.init_db(setup)
    setup.close()

    day = _next_weekday(config, 4)
    attempts = 24
    barrier = threading.Barrier(attempts)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        conn = db.connect(db_path)
        try:
            barrier.wait(timeout=10)
            try:
                create_booking(conn, config, FakeRequest(day, "09:00", f"Racer {index}"))
                with lock:
                    outcomes.append("won")
            except BookingConflict:
                with lock:
                    outcomes.append("conflict")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"error:{type(exc).__name__}:{exc}")
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    wins = outcomes.count("won")
    conflicts = outcomes.count("conflict")
    errors = [o for o in outcomes if o.startswith("error")]

    check(f"concurrency: {attempts} simultaneous requests produce exactly 1 winner",
          wins == 1, f"winners={wins} conflicts={conflicts} errors={errors[:3]}")
    check(f"concurrency: the other {attempts - 1} get a 409 conflict, none error",
          conflicts == attempts - 1 and not errors,
          f"conflicts={conflicts} errors={errors[:3]}")

    verify = db.connect(db_path)
    rows = verify.execute(
        "SELECT COUNT(*) AS n FROM bookings WHERE local_date = ? AND local_time = ? "
        "AND status IN ('Pending','Confirmed')",
        (day.isoformat(), "09:00"),
    ).fetchone()
    check("concurrency: database holds exactly one row for that slot",
          int(rows["n"]) == 1, f"rows={rows['n']}")
    verify.close()


def test_concurrent_different_slots(tmp: Path) -> None:
    """Parallel pressure must not lose legitimate bookings."""
    config = load_config(_tmp_config(tmp))
    db_path = tmp / "many.db"
    setup = db.connect(db_path)
    db.init_db(setup)
    setup.close()

    day = _next_weekday(config, 1)
    slots = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    barrier = threading.Barrier(len(slots))
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(clock: str, index: int) -> None:
        conn = db.connect(db_path)
        try:
            barrier.wait(timeout=10)
            try:
                create_booking(conn, config, FakeRequest(day, clock, f"Guest {index}"))
                with lock:
                    outcomes.append("ok")
            except BookingConflict:
                with lock:
                    outcomes.append("conflict")
        finally:
            conn.close()

    threads = [
        threading.Thread(target=worker, args=(clock, i)) for i, clock in enumerate(slots)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    check("load: 8 different slots booked in parallel all succeed",
          outcomes.count("ok") == len(slots), f"{outcomes}")

    verify = db.connect(db_path)
    total = verify.execute(
        "SELECT COUNT(*) AS n FROM bookings WHERE local_date = ?", (day.isoformat(),)
    ).fetchone()
    check("load: all 8 rows persisted", int(total["n"]) == len(slots), f"rows={total['n']}")
    verify.close()


def test_booking_closed_safety_switch(tmp: Path) -> None:
    config = load_config(_tmp_config(tmp, opening_closed_until_YYYY_MM_DD="2099-01-01"))
    conn = db.connect(tmp / "f.db")
    db.init_db(conn)
    day = _next_weekday(config, 0)
    try:
        create_booking(conn, config, FakeRequest(day, "09:00"))
        check("safety: booking refused while opening_closed_until is in the future", False)
    except Exception as exc:
        check("safety: booking refused while opening_closed_until is in the future",
              type(exc).__name__ == "BookingClosed", type(exc).__name__)
    conn.close()


def test_validation_rules(tmp: Path) -> None:
    from .validate import ValidationError, validate_booking

    config = load_config(_tmp_config(tmp))
    base = {
        "full_name": "Jane Smith",
        "phone": "07784044111",
        "email": "jane@example.com",
        "service_type": "painting",
        "property_address": "12 Example Street",
        "postcode": "SW1A 1AA",
        "job_description": "Repaint the hallway",
        "requested_date": "2026-06-10",
        "requested_time": "10:00",
    }

    ok = validate_booking(base, config.service_types)
    check("validation: a valid payload passes", ok.postcode == "SW1A 1AA")

    def rejects(mutate, field):
        payload = dict(base)
        mutate(payload)
        try:
            validate_booking(payload, config.service_types)
            return False, "accepted"
        except ValidationError as exc:
            return exc.field == field, exc.field

    passed, detail = rejects(lambda p: p.update(email="not-an-email"), "email")
    check("validation: rejects a bad email", passed, detail)

    passed, detail = rejects(lambda p: p.update(postcode="!!!"), "postcode")
    check("validation: rejects a bad postcode", passed, detail)

    passed, detail = rejects(lambda p: p.update(service_type="plumbing"), "service_type")
    check("validation: rejects a service not in config", passed, detail)

    passed, detail = rejects(lambda p: p.pop("phone"), "phone")
    check("validation: rejects a missing phone", passed, detail)

    passed, detail = rejects(lambda p: p.update(website="http://spam"), "website")
    check("validation: honeypot field is rejected", passed, detail)

    passed, detail = rejects(
        lambda p: p.update(requested_time="25:00"), "requested_time"
    )
    check("validation: rejects an impossible time", passed, detail)


def test_password_hashing(tmp: Path) -> None:
    stored = db.hash_password("correct horse battery")
    check("security: correct password verifies", db.verify_password("correct horse battery", stored))
    check("security: wrong password rejected", not db.verify_password("wrong", stored))
    check("security: hash is not the plaintext", "correct horse" not in stored)

    conn = db.connect(tmp / "g.db")
    db.init_db(conn)
    db.upsert_admin(conn, "admin", "a-long-enough-password")
    row = db.get_admin(conn, "admin")
    check("security: admin row stored", row is not None)
    check("security: admin password not stored in plaintext",
          row is not None and "a-long-enough-password" not in row["password_hash"])
    conn.close()


def test_config_validation(tmp: Path) -> None:
    from .config import ConfigError

    bad = tmp / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "appointment_duration_minutes": 60,
                "slot_granularity_minutes": 30,
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
                "min_notice_hours": 0,
                "max_advance_days": 60,
                "booking_horizon_days": 60,
                "working_hours": {"mon": [["17:00", "09:00"]]},
                "service_types": ["painting"],
            }
        ),
        encoding="utf-8",
    )
    try:
        load_config(bad)
        check("config: a window that ends before it starts is rejected", False)
    except ConfigError as exc:
        check("config: a window that ends before it starts is rejected",
              "ends before it starts" in str(exc), str(exc))

    granularity = tmp / "granularity.json"
    granularity.write_text(
        json.dumps(
            {
                "appointment_duration_minutes": 30,
                "slot_granularity_minutes": 60,
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
                "min_notice_hours": 0,
                "max_advance_days": 60,
                "booking_horizon_days": 60,
                "working_hours": {"mon": [["09:00", "17:00"]]},
                "service_types": ["painting"],
            }
        ),
        encoding="utf-8",
    )
    try:
        load_config(granularity)
        check("config: granularity larger than duration is rejected", False)
    except ConfigError as exc:
        check("config: granularity larger than duration is rejected",
              "larger than" in str(exc), str(exc))


# --------------------------------------------------------------------------
# End to end, through the real HTTP server
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _http_call(base: str, path: str, method: str = "GET", body=None, headers=None):
    import urllib.error
    import urllib.request

    payload = None
    request_headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        base + path, data=payload, method=method, headers=request_headers
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            status, response_headers = response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status, response_headers = exc.code, dict(exc.headers)

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {"_text": raw.decode("utf-8", "replace")}
    return status, data, response_headers


def test_http_end_to_end(tmp: Path) -> None:
    """Everything a real customer does, over a real socket.

    This is the test that catches integration mistakes the unit checks miss: a
    route that does not exist, a field name that does not match the form, a
    cookie that is never returned, a CSRF header the server never reads.
    """
    from http.server import ThreadingHTTPServer

    from .http_app import App, build_handler

    config_path = _tmp_config(tmp, min_notice_hours=0)
    config = load_config(config_path)
    app = App(config, tmp / "http.db", PROJECT_ROOT, tmp / "session.key")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(app, False))
    httpd.daemon_threads = True
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    base = "http://127.0.0.1:%d" % httpd.server_address[1]

    try:
        status, data, _ = _http_call(base, "/api/health")
        check("http: health endpoint answers", status == 200 and data.get("ok") is True)

        status, data, _ = _http_call(base, "/api/booking/config")
        check("http: public config exposes the service ids",
              status == 200 and "painting" in data.get("service_types", []),
              str(data)[:120])
        check("http: public config sends today's date in the site timezone",
              len(data.get("today", "")) == 10, data.get("today"))

        day = _next_weekday(config, 2).isoformat()
        year, month_number = day[:4], int(day[5:7])

        status, month, _ = _http_call(
            base, "/api/booking/month?year=%s&month=%s" % (year, month_number)
        )
        check("http: month endpoint describes the days",
              status == 200 and day in month.get("days", {}), str(month)[:120])

        status, availability_payload, _ = _http_call(
            base, "/api/booking/availability?date=" + day
        )
        free_slots = [s for s in availability_payload.get("slots", [])
                      if s.get("available")]
        check("http: availability returns bookable slots",
              status == 200 and bool(free_slots), str(availability_payload)[:120])
        if not free_slots:
            return
        clock = free_slots[0]["time"]

        booking = {
            "full_name": "Jane Smith",
            "phone": "07784044111",
            "email": "jane@example.com",
            "service_type": "painting",
            "property_address": "12 Example Street",
            "postcode": "SW1A 1AA",
            "job_description": "Repaint the hallway and fix the front door lock",
            "requested_date": day,
            "requested_time": clock,
        }

        status, data, _ = _http_call(base, "/api/booking", "POST", booking)
        check("http: a valid booking returns 201 with a reference",
              status == 201 and str(data.get("reference", "")).startswith("FM-"),
              "%s %s" % (status, str(data)[:120]))
        check("http: the response confirms Pending",
              data.get("status") == "Pending", data.get("status"))

        status, data, _ = _http_call(base, "/api/booking", "POST", booking)
        check("http: booking the same slot twice returns 409",
              status == 409, "%s %s" % (status, str(data)[:120]))
        check("http: the 409 message is the required wording",
              data.get("message") == CONFLICT_MESSAGE, str(data.get("message")))

        incomplete = dict(booking)
        del incomplete["postcode"]
        status, data, _ = _http_call(base, "/api/booking", "POST", incomplete)
        check("http: a missing field returns 400 naming the field",
              status == 400 and data.get("field") == "postcode",
              "%s %s" % (status, str(data)[:120]))

        spam = dict(booking)
        spam["website"] = "http://spam.example"
        if len(free_slots) > 1:
            spam["requested_time"] = free_slots[1]["time"]
        status, data, _ = _http_call(base, "/api/booking", "POST", spam)
        check("http: the honeypot field is rejected",
              status == 400 and data.get("field") == "website",
              "%s %s" % (status, str(data)[:120]))

        status, data, _ = _http_call(base, "/api/booking/availability?date=" + day)
        taken = [s for s in data.get("slots", []) if s.get("time") == clock]
        check("http: the booked slot now shows as unavailable",
              bool(taken) and taken[0].get("available") is False
              and taken[0].get("reason") == "booked",
              str(taken)[:120])

        status, _, _ = _http_call(base, "/api/booking/availability?date=2001-01-01")
        check("http: a date in the past is refused with 400", status == 400,
              str(status))

        for page in ("/", "/booking.js", "/admin.html", "/styles.css"):
            status, data, _ = _http_call(base, page)
            check("http: %s is served" % page,
                  status == 200 and len(data.get("_text", "")) > 0, str(status))

        status, _, _ = _http_call(base, "/../../server/config.json")
        check("http: path traversal does not leak a file",
              status in (403, 404), str(status))

        status, _, _ = _http_call(base, "/api/admin/bookings")
        check("http: the admin list refuses an anonymous caller", status == 401,
              str(status))

        status, _, _ = _http_call(base, "/api/admin/login", "POST",
                                  {"username": "admin", "password": "wrong"})
        check("http: a wrong password is refused with 401", status == 401, str(status))

        db.upsert_admin(app.conn(), config.admin_username, "correct-horse-battery")

        status, data, headers = _http_call(base, "/api/admin/login", "POST", {
            "username": config.admin_username,
            "password": "correct-horse-battery",
        })
        cookie = headers.get("Set-Cookie", "")
        check("http: correct credentials return 200 and a session cookie",
              status == 200 and "fixmate_admin=" in cookie and "HttpOnly" in cookie,
              "%s %s" % (status, cookie[:80]))
        csrf = data.get("csrf", "")
        jar = {"Cookie": cookie.split(";")[0]}

        status, data, _ = _http_call(base, "/api/admin/bookings", headers=jar)
        check("http: the signed-in admin sees the booking",
              status == 200 and len(data.get("bookings", [])) == 1,
              "%s %s" % (status, str(data)[:160]))

        listing = data.get("bookings", [])
        booking_id = listing[0].get("id", "") if listing else ""
        summary = listing[0].get("summary", "") if listing else ""
        check("http: the admin list renders a customer-friendly summary",
              ", " in summary and "(" in summary, summary)

        status, data, _ = _http_call(
            base, "/api/admin/bookings/%s/status" % booking_id,
            "POST", {"status": "Confirmed"}, headers=jar,
        )
        check("http: an admin write without the CSRF header is refused",
              status == 403, "%s %s" % (status, str(data)[:120]))

        signed = dict(jar)
        signed["X-FixMate-CSRF"] = csrf
        status, data, _ = _http_call(
            base, "/api/admin/bookings/%s/status" % booking_id,
            "POST", {"status": "Confirmed"}, headers=signed,
        )
        check("http: confirming with the CSRF header works",
              status == 200 and data.get("booking", {}).get("status") == "Confirmed",
              "%s %s" % (status, str(data)[:160]))

        status, data, _ = _http_call(
            base, "/api/admin/bookings/%s/status" % booking_id,
            "POST", {"status": "Cancelled"}, headers=signed,
        )
        check("http: cancelling works",
              status == 200 and data.get("booking", {}).get("status") == "Cancelled",
              "%s %s" % (status, str(data)[:160]))

        rebooked = dict(booking)
        rebooked["full_name"] = "Second Customer"
        status, data, _ = _http_call(base, "/api/booking", "POST", rebooked)
        check("http: a cancelled slot can be booked again",
              status == 201, "%s %s" % (status, str(data)[:120]))

        status, _, headers = _http_call(base, "/api/admin/logout", "POST", {},
                                        headers=signed)
        check("http: logout clears the cookie",
              status == 200 and "Max-Age=0" in headers.get("Set-Cookie", ""),
              "%s %s" % (status, headers.get("Set-Cookie", "")[:60]))
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)
        app.close()


def run() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        tests = [
            test_availability_basics,
            test_availability_holiday_and_closure,
            test_availability_min_notice,
            test_buffer_windows,
            test_dst_transitions,
            test_booking_success_and_conflict,
            test_cancel_frees_the_slot,
            test_concurrent_same_slot,
            test_concurrent_different_slots,
            test_booking_closed_safety_switch,
            test_validation_rules,
            test_password_hashing,
            test_config_validation,
            test_http_end_to_end,
        ]
        for test in tests:
            try:
                test(tmp)
            except Exception:  # noqa: BLE001
                RESULTS.append((test.__name__, False, traceback.format_exc(limit=3)))

    width = max(len(name) for name, _, _ in RESULTS)
    passed = 0
    print("=" * (width + 12))
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name.ljust(width)}  {'' if ok else detail}")
        if ok:
            passed += 1
    print("=" * (width + 12))
    print(f"  {passed}/{len(RESULTS)} checks passed")

    critical = [n for n, ok, _ in RESULTS if not ok and "concurrency" in n]
    if critical:
        print("\n  DOUBLE-BOOKING PROTECTION IS NOT PROVEN. Do not go live.")
        return 1
    if passed != len(RESULTS):
        print("\n  Some checks failed. Fix them before going live.")
        return 1
    print("\n  All checks passed, including concurrent-slot protection.")
    return 0


if __name__ == "__main__":
    sys.exit(run())