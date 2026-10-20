"""Booking creation.

create_booking() is the only path that writes a booking, and it does three
things in this order:

  1. BEGIN IMMEDIATE, so the availability check and the insert share one
     exclusive write transaction and cannot be interleaved by another writer.
  2. Re-check the slot against the database, inside that transaction.
  3. INSERT, relying on ux_bookings_active_slot to reject a duplicate even if
     step 2 somehow passed.

Steps 2 and 3 are deliberately redundant. The unique index is the guarantee;
the re-check exists so the customer gets the specific "just booked" message
instead of a generic database error.

Without BEGIN IMMEDIATE a check-then-insert race is possible: two requests both
read "free", both pass, both insert. The index still stops the second write, but
the user-facing error would be wrong. IMMEDIATE removes the window.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import db
from .availability import REASON_BOOKED, is_slot_available
from .config import Config
from .tz import (
    format_for_customer,
    parse_clock,
    today_in,
    utc_iso,
    utc_offset_minutes,
    wall_clock_to_utc,
)

CONFLICT_MESSAGE = (
    "Sorry, this time slot has just been booked. Please choose another available time."
)

REASON_TEXT = {
    "booked": CONFLICT_MESSAGE,
    "insufficient_notice": "That time is now too close to book. Please choose a later time.",
    "beyond_horizon": "That date is too far ahead to book yet.",
    "closed": "We are not open at that time. Please choose another available time.",
    "dst_gap": "That time does not exist on this date because the clocks change.",
    "past": "That time has already passed. Please choose another available time.",
}


class BookingConflict(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.message = REASON_TEXT.get(reason, REASON_TEXT[REASON_BOOKED])
        self.status_code = 409


class BookingClosed(Exception):
    def __init__(self, message: str = "Booking is temporarily closed."):
        super().__init__(message)
        self.message = message
        self.status_code = 503


@dataclass(frozen=True)
class BookingResult:
    booking_id: str
    reference: str
    status: str
    local_date: str
    local_time: str
    starts_at_utc: str
    utc_offset_minutes: int
    customer_line: str


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _is_slot_violation(exc: sqlite3.IntegrityError) -> bool:
    """True only when the UNIQUE active-slot index is what rejected the write."""
    text = str(exc)
    return (
        "ux_bookings_active_slot" in text
        or "bookings.local_date, bookings.local_time" in text
    )


def _assert_open(config: Config) -> None:
    today = today_in(config.zone)
    if today.isoformat() < config.opening_closed_until:
        raise BookingClosed(
            f"Booking opens on {config.opening_closed_until}. "
            "Please call or WhatsApp us in the meantime."
        )


def create_booking(
    conn: sqlite3.Connection,
    config: Config,
    request,
    reference_now=None,
) -> BookingResult:
    _assert_open(config)

    zone: ZoneInfo = config.zone
    day = request.requested_date
    clock = parse_clock(request.requested_time)

    start_utc = wall_clock_to_utc(day, clock, zone)
    if start_utc is None:
        raise BookingConflict("dst_gap")
    end_utc = start_utc + timedelta(minutes=config.appointment_duration_minutes)

    booking_id = db.new_id()
    reference = db.new_reference()

    conn.execute("BEGIN IMMEDIATE")
    try:
        available, reason = is_slot_available(
            conn, config, day, request.requested_time, reference_now
        )
        if not available:
            conn.execute("ROLLBACK")
            raise BookingConflict(reason)

        db.insert_booking(
            conn,
            {
                "id": booking_id,
                "reference": reference,
                "status": "Pending",
                "local_date": day.isoformat(),
                "local_time": clock.strftime("%H:%M"),
                "utc_offset_minutes": utc_offset_minutes(start_utc, zone),
                "starts_at_utc": utc_iso(start_utc),
                "ends_at_utc": utc_iso(end_utc),
                "duration_minutes": config.appointment_duration_minutes,
                "full_name": request.full_name,
                "phone": request.phone,
                "email": request.email,
                "service_type": request.service_type,
                "property_address": request.property_address,
                "postcode": request.postcode,
                "job_description": request.job_description,
                "created_at_utc": db.utc_now_iso(),
                "updated_at_utc": db.utc_now_iso(),
            },
        )
        db.add_event(conn, booking_id, None, "Pending", "customer", "created online")
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        _rollback(conn)
        if _is_slot_violation(exc):
            raise BookingConflict(REASON_BOOKED) from None
        # Anything else is a real fault, not a booking clash. Letting it
        # propagate means a 500 and a logged traceback instead of telling a
        # customer their slot was taken when it was not.
        raise
    except Exception:
        _rollback(conn)
        raise

    offset = utc_offset_minutes(start_utc, zone)
    return BookingResult(
        booking_id=booking_id,
        reference=reference,
        status="Pending",
        local_date=day.isoformat(),
        local_time=clock.strftime("%H:%M"),
        starts_at_utc=utc_iso(start_utc),
        utc_offset_minutes=offset,
        customer_line=format_for_customer(
            day.isoformat(), clock.strftime("%H:%M"), offset
        ),
    )


__all__ = [
    "BookingClosed",
    "BookingConflict",
    "BookingResult",
    "CONFLICT_MESSAGE",
    "REASON_TEXT",
    "create_booking",
]