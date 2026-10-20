"""Configuration loading and validation.

The owner edits server/config.json. Everything the availability engine decides
lives there, so nothing about working hours, holidays or appointment length is
baked into the code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tz import DEFAULT_TIMEZONE, WEEKDAY_KEYS, get_zone, parse_clock

_PLACEHOLDER_KEYS = (
    "confirm_before_launch",
    "confirm_before_launch_duration",
    "confirm_before_launch_granularity",
    "confirm_before_launch_min_notice",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    start: str
    end: str


@dataclass(frozen=True)
class Config:
    timezone_name: str
    locale: str
    appointment_duration_minutes: int
    slot_granularity_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    min_notice_hours: int
    max_advance_days: int
    booking_horizon_days: int
    busy_statuses: tuple[str, ...]
    show_booked_slots: bool
    holidays: frozenset[str]
    closures: frozenset[str]
    working_hours: dict[str, tuple[Window, ...]]
    service_types: tuple[str, ...]
    opening_closed_until: str
    admin_session_ttl_hours: int
    admin_username: str
    notify_enabled: bool
    notify_webhook_env: str
    notify_secret_env: str
    notify_timeout_seconds: int
    source_path: Path
    zone: Any = field(repr=False, default=None)

    @property
    def placeholders_remaining(self) -> tuple[str, ...]:
        return _PLACEHOLDER_KEYS


def _require_int(data: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key} must be a whole number, got {value!r}")
    if value < minimum or value > maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got {value}")
    return value


def _parse_windows(raw: Any, key: str) -> tuple[Window, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"working_hours.{key} must be a list of windows")
    windows: list[Window] = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ConfigError(
                f"working_hours.{key} entries must be [start, end] pairs, got {entry!r}"
            )
        start, end = str(entry[0]), str(entry[1])
        try:
            start_clock = parse_clock(start)
            end_clock = parse_clock(end)
        except ValueError as exc:
            raise ConfigError(f"working_hours.{key}: {exc}") from exc
        if end_clock <= start_clock:
            raise ConfigError(
                f"working_hours.{key}: window {start}-{end} ends before it starts"
            )
        windows.append(Window(start=start, end=end))
    windows.sort(key=lambda w: w.start)
    return tuple(windows)


def _parse_date_set(raw: Any, key: str) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ConfigError(f"{key} must be a list of YYYY-MM-DD strings")
    values = set()
    for item in raw:
        text = str(item)
        if len(text) != 10 or text[4] != "-" or text[7] != "-":
            raise ConfigError(f"{key} entries must look like YYYY-MM-DD, got {text!r}")
        values.add(text)
    return frozenset(values)


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config must be a JSON object")

    tz_name = str(raw.get("timezone", DEFAULT_TIMEZONE))
    zone = get_zone(tz_name)

    duration = _require_int(raw, "appointment_duration_minutes", 5, 12 * 60)
    granularity = _require_int(raw, "slot_granularity_minutes", 5, 24 * 60)
    if granularity > duration:
        raise ConfigError(
            "slot_granularity_minutes cannot be larger than appointment_duration_minutes"
        )

    busy = raw.get("busy_statuses") or ["Pending", "Confirmed"]
    if not isinstance(busy, list) or not busy:
        raise ConfigError("busy_statuses must be a non-empty list")
    allowed_statuses = {"Pending", "Confirmed", "Cancelled"}
    unknown = [s for s in busy if s not in allowed_statuses]
    if unknown:
        raise ConfigError(f"busy_statuses contains unknown status: {unknown}")

    raw_hours = raw.get("working_hours")
    if not isinstance(raw_hours, dict):
        raise ConfigError("working_hours must be an object keyed by weekday")
    hours: dict[str, tuple[Window, ...]] = {}
    for key, value in raw_hours.items():
        if key == "_readme":
            continue
        if key not in WEEKDAY_KEYS:
            raise ConfigError(f"working_hours has unknown weekday key {key!r}")
        hours[key] = _parse_windows(value, key)

    services = raw.get("service_types") or []
    if isinstance(services, dict):
        services = list(services.keys())
    if not isinstance(services, list) or not services:
        raise ConfigError("service_types must be a non-empty list of service ids")
    service_ids = tuple(str(s) for s in services if not str(s).startswith("_"))

    admin = raw.get("admin") or {}
    notify = raw.get("notify") or {}

    return Config(
        timezone_name=tz_name,
        locale=str(raw.get("locale", "en-GB")),
        appointment_duration_minutes=duration,
        slot_granularity_minutes=granularity,
        buffer_before_minutes=_require_int(raw, "buffer_before_minutes", 0, 12 * 60),
        buffer_after_minutes=_require_int(raw, "buffer_after_minutes", 0, 12 * 60),
        min_notice_hours=_require_int(raw, "min_notice_hours", 0, 24 * 30),
        max_advance_days=_require_int(raw, "max_advance_days", 1, 730),
        booking_horizon_days=_require_int(raw, "booking_horizon_days", 1, 730),
        busy_statuses=tuple(str(s) for s in busy),
        show_booked_slots=bool(raw.get("show_booked_slots", False)),
        holidays=_parse_date_set(raw.get("holidays"), "holidays"),
        closures=_parse_date_set(raw.get("closures"), "closures"),
        working_hours=hours,
        service_types=service_ids,
        opening_closed_until=str(raw.get("opening_closed_until_YYYY_MM_DD", "2000-01-01")),
        admin_session_ttl_hours=int(admin.get("session_ttl_hours", 12)),
        admin_username=str(admin.get("username", "admin")),
        notify_enabled=bool(notify.get("enabled", False)),
        notify_webhook_env=str(notify.get("webhook_url_env", "N8N_BOOKING_WEBHOOK_URL")),
        notify_secret_env=str(notify.get("secret_env", "N8N_WEBHOOK_SECRET")),
        notify_timeout_seconds=int(notify.get("timeout_seconds", 8)),
        source_path=config_path,
        zone=zone,
    )


def is_accepting_bookings(config: Config, today_iso: str) -> bool:
    return today_iso >= config.opening_closed_until


__all__ = ["Config", "ConfigError", "Window", "is_accepting_bookings", "load_config"]