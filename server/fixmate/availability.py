"""Availability engine.

Two entry points:

    slots_for_date()  the customer-facing grid for one day
    describe_range()  a summary of which days are open, for the month calendar

Everything is computed from server/config.json plus what is already in the
database. The client never decides whether a time is free; it only renders what
this module returns. The result is still re-verified inside the booking
transaction, because availability shown at 10:00 and availability at the moment
of saving are different questions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Config
from .tz import (
    WEEKDAY_KEYS,
    add_days,
    now_utc,
    parse_clock,
    wall_clock_to_utc,
)

REASON_CLOSED = "closed"
REASON_BOOKED = "booked"
REASON_PAST = "past"
REASON_NOTICE = "insufficient_notice"
REASON_HORIZON = "beyond_horizon"
REASON_DST = "dst_gap"


@dataclass(frozen=True)
class Slot:
    local_date: str
    local_time: str
    available: bool
    reason: str = ""
    starts_at_utc: str = ""


def _window_bounds(window) -> tuple[time, time]:
    return parse_clock(window.start), parse_clock(window.end)


def window_slot_range(config: Config, window) -> tuple[time, time] | None:
    """First and last bookable start inside one working window, or None.

    The two buffers are edge buffers, not gaps between jobs: buffer_before is
    time the owner needs at the start of the day (setup, travel, parking), so
    the first customer cannot arrive earlier than window_start + buffer_before;
    buffer_after is time needed before closing, so the last job must end by
    window_end - buffer_after.

    slots_for_date() and is_slot_available() both call this. They must agree
    exactly, otherwise the grid offers a slot that the booking transaction then
    refuses.
    """
    start_clock, end_clock = _window_bounds(window)
    midnight = datetime(2000, 1, 1)
    first = midnight + timedelta(
        hours=start_clock.hour,
        minutes=start_clock.minute + config.buffer_before_minutes,
    )
    last = (
        midnight
        + timedelta(hours=end_clock.hour, minutes=end_clock.minute)
        - timedelta(minutes=config.appointment_duration_minutes)
        - timedelta(minutes=config.buffer_after_minutes)
    )
    if last < first:
        return None
    return first.time(), last.time()


def _slot_start_times(
    config: Config, day: date
) -> list[tuple[time, time, str]]:
    """Every candidate start clock for one day: (slot_time, latest_start, window_start)."""
    key = WEEKDAY_KEYS[day.weekday()]
    windows = config.working_hours.get(key, ())
    out: list[tuple[time, time, str]] = []
    for window in windows:
        bounds = window_slot_range(config, window)
        if bounds is None:
            continue
        first, last = bounds
        cursor = datetime.combine(day, first)
        step = timedelta(minutes=config.slot_granularity_minutes)
        while cursor.time() <= last:
            out.append((cursor.time(), last, window.start))
            cursor += step
    return out


def _is_booked(
    slot_utc: datetime,
    end_utc: datetime,
    busy: list[tuple[datetime, datetime]],
) -> bool:
    for busy_start, busy_end in busy:
        if slot_utc < busy_end and end_utc > busy_start:
            return True
    return False


def slots_for_date(
    conn: sqlite3.Connection,
    config: Config,
    day: date,
    reference_now: datetime | None = None,
    include_booked: bool | None = None,
) -> list[Slot]:
    """Every candidate start time on one local date, with availability attached.

    reference_now exists so tests can freeze time; production always uses the
    real clock.
    """
    zone: ZoneInfo = config.zone
    now = reference_now or now_utc()
    day_iso = day.isoformat()

    include = (
        config.show_booked_slots if include_booked is None else include_booked
    )

    # Every "today" here is derived from `now`, never from the wall clock, so a
    # frozen test clock produces a frozen result.
    today = now.astimezone(zone).date()
    earliest = now + timedelta(hours=config.min_notice_hours)
    horizon = now + timedelta(days=config.booking_horizon_days)
    horizon_day = min(
        horizon.astimezone(zone).date(),
        today + timedelta(days=config.max_advance_days),
    )

    if day_iso in config.holidays or day_iso in config.closures:
        return []

    rows = conn.execute(
        "SELECT local_time, starts_at_utc, ends_at_utc, utc_offset_minutes "
        "FROM bookings WHERE local_date = ? AND status IN "
        f"({', '.join('?' for _ in config.busy_statuses)})",
        (day_iso, *config.busy_statuses),
    ).fetchall()

    busy: list[tuple[datetime, datetime]] = []
    for row in rows:
        busy.append(
            (
                datetime.strptime(row["starts_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                ),
                datetime.strptime(row["ends_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                ),
            )
        )

    results: list[Slot] = []
    for slot_time, _latest, _win_start in _slot_start_times(config, day):
        start_utc = wall_clock_to_utc(day, slot_time, zone)
        if start_utc is None:
            if include:
                results.append(Slot(day_iso, slot_time.strftime("%H:%M"), False, REASON_DST))
            continue

        end_utc = start_utc + timedelta(minutes=config.appointment_duration_minutes)
        clock = slot_time.strftime("%H:%M")

        if day < today:
            if include:
                results.append(Slot(day_iso, clock, False, REASON_PAST))
            continue
        if day > horizon_day:
            if include:
                results.append(Slot(day_iso, clock, False, REASON_HORIZON))
            continue
        if start_utc < earliest:
            if include:
                results.append(Slot(day_iso, clock, False, REASON_NOTICE))
            continue
        if _is_booked(start_utc, end_utc, busy):
            if include:
                results.append(
                    Slot(day_iso, clock, False, REASON_BOOKED, _iso(start_utc))
                )
            continue

        results.append(Slot(day_iso, clock, True, "", _iso(start_utc)))

    return results


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def available_times(
    conn: sqlite3.Connection,
    config: Config,
    day: date,
    reference_now: datetime | None = None,
) -> list[str]:
    return [s.local_time for s in slots_for_date(conn, config, day, reference_now)
            if s.available]


def is_slot_available(
    conn: sqlite3.Connection,
    config: Config,
    day: date,
    clock: str,
    reference_now: datetime | None = None,
) -> tuple[bool, str]:
    """Server-side re-check. Returns (available, reason)."""
    zone: ZoneInfo = config.zone
    slot_time = parse_clock(clock)
    start_utc = wall_clock_to_utc(day, slot_time, zone)
    if start_utc is None:
        return False, REASON_DST

    now = reference_now or now_utc()
    if start_utc < now + timedelta(hours=config.min_notice_hours):
        return False, REASON_NOTICE
    if start_utc > now + timedelta(days=config.booking_horizon_days):
        return False, REASON_HORIZON

    key = WEEKDAY_KEYS[day.weekday()]
    windows = config.working_hours.get(key, ())
    inside = False
    for window in windows:
        bounds = window_slot_range(config, window)
        if bounds is None:
            continue
        first, last = bounds
        if first <= slot_time <= last:
            inside = True
            break
    if not inside:
        return False, REASON_CLOSED

    end_utc = start_utc + timedelta(minutes=config.appointment_duration_minutes)
    rows = conn.execute(
        "SELECT starts_at_utc, ends_at_utc FROM bookings WHERE local_date = ? "
        f"AND status IN ({', '.join('?' for _ in config.busy_statuses)})",
        (day.isoformat(), *config.busy_statuses),
    ).fetchall()
    busy = [
        (
            datetime.strptime(r["starts_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
            datetime.strptime(r["ends_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
        )
        for r in rows
    ]
    if _is_booked(start_utc, end_utc, busy):
        return False, REASON_BOOKED
    return True, ""


def describe_range(
    conn: sqlite3.Connection,
    config: Config,
    first: date,
    last: date,
    reference_now: datetime | None = None,
) -> dict[str, dict]:
    """Per-day open/closed summary so the calendar can grey out dead dates."""
    now = reference_now or now_utc()
    zone: ZoneInfo = config.zone
    today = now.astimezone(zone).date()

    summary: dict[str, dict] = {}
    cursor = first
    while cursor <= last:
        key = cursor.isoformat()
        weekday = WEEKDAY_KEYS[cursor.weekday()]
        windows = config.working_hours.get(weekday, ())

        if key in config.holidays or key in config.closures:
            summary[key] = {"open": False, "reason": REASON_CLOSED, "free": 0}
        elif cursor < today:
            summary[key] = {"open": False, "reason": REASON_PAST, "free": 0}
        else:
            slots = slots_for_date(conn, config, cursor, now)
            free = len([s for s in slots if s.available])
            has_window = bool(windows)
            summary[key] = {
                "open": free > 0,
                "reason": "" if free > 0 else (REASON_NOTICE if has_window else REASON_CLOSED),
                "free": free,
            }
        cursor = add_days(cursor, 1)

    return summary


__all__ = [
    "REASON_BOOKED",
    "REASON_CLOSED",
    "REASON_DST",
    "REASON_HORIZON",
    "REASON_NOTICE",
    "REASON_PAST",
    "Slot",
    "available_times",
    "describe_range",
    "is_slot_available",
    "slots_for_date",
    "window_slot_range",
]