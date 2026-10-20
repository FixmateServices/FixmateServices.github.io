"""Timezone helpers for the booking engine.

Every instant that crosses the process boundary is UTC ISO-8601 with a Z
suffix. Every wall-clock value the customer sees or types is Europe/London.

The two are kept in separate columns in the bookings table so a slot is always
identified by the wall clock the owner actually thinks in ("Friday 09:00"),
while comparisons and conflict detection happen on unambiguous UTC instants.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/London"

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_OFFSET_RE = re.compile(r"^(?P<body>\d{4}-\d{2}-\d{2})[T ](?P<time>\d{2}:\d{2})$")


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unknown timezone {name!r}. The host needs the IANA tz database "
            f"(tzdata package on Windows, or /usr/share/zoneinfo on Linux)."
        ) from exc


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_utc_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def utc_offset_minutes(value: datetime, tz: ZoneInfo) -> int:
    offset = value.astimezone(tz).utcoffset()
    if offset is None:
        raise ValueError("Could not resolve a UTC offset")
    return int(offset.total_seconds() // 60)


def local_date_of(value: datetime, tz: ZoneInfo) -> str:
    return value.astimezone(tz).strftime("%Y-%m-%d")


def local_time_of(value: datetime, tz: ZoneInfo) -> str:
    return value.astimezone(tz).strftime("%H:%M")


def parse_local_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def wall_clock_to_utc(day: date, clock: time, tz: ZoneInfo) -> datetime | None:
    """Convert a Europe/London wall clock to a UTC instant.

    Returns None when that wall clock does not exist, which happens for one
    hour every spring when the clocks go forward. The round-trip check is what
    makes this safe: a naive replace(tzinfo=...) would silently invent 01:30 on
    a day that has no 01:30, and the booking would land an hour out.
    """
    local = datetime.combine(day, clock).replace(tzinfo=tz, fold=0)
    utc = local.astimezone(timezone.utc)
    back = utc.astimezone(tz)
    if (back.year, back.month, back.day, back.hour, back.minute) != (
        day.year,
        day.month,
        day.day,
        clock.hour,
        clock.minute,
    ):
        return None
    return utc.replace(microsecond=0)


def is_ambiguous_wall_clock(day: date, clock: time, tz: ZoneInfo) -> bool:
    """True when a wall clock occurs twice (autumn, clocks go back)."""
    first = datetime.combine(day, clock).replace(tzinfo=tz, fold=0)
    second = datetime.combine(day, clock).replace(tzinfo=tz, fold=1)
    return first.utcoffset() != second.utcoffset()


def parse_offset_minutes(value: str) -> int:
    total = 0
    sign = 1
    if value.startswith("-"):
        sign = -1
    body = value[1:] if value[:1] in "+-" else value
    hours, _, minutes = body.partition(":")
    total += int(hours) * 60
    if minutes:
        total += int(minutes)
    return sign * total


def format_for_customer(day: str, clock: str, offset_minutes: int) -> str:
    """Render 'Friday 13 March 2026, 09:00 (GMT)' without relying on locale data."""
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return f"{day} {clock}"
    weekday = WEEKDAY_KEYS[parsed.weekday()].capitalize()
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    label = f"{weekday} {parsed.day} {months[parsed.month - 1]} {parsed.year}"
    suffix = "GMT" if offset_minutes == 0 else "BST"
    return f"{label}, {clock} ({suffix})"


def today_in(tz: ZoneInfo) -> date:
    return datetime.now(timezone.utc).astimezone(tz).date()


def days_between(start: date, end: date) -> int:
    return (end - start).days


def add_days(day: date, count: int) -> date:
    return day + timedelta(days=count)


__all__ = [
    "DEFAULT_TIMEZONE",
    "WEEKDAY_KEYS",
    "add_days",
    "days_between",
    "format_for_customer",
    "from_utc_iso",
    "get_zone",
    "is_ambiguous_wall_clock",
    "local_date_of",
    "local_time_of",
    "now_utc",
    "parse_clock",
    "parse_local_date",
    "parse_offset_minutes",
    "today_in",
    "utc_iso",
    "utc_offset_minutes",
    "wall_clock_to_utc",
]