"""Request payload validation.

The API trusts nothing. Every field the customer sends is length-checked and
type-checked here, before any database work happens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
PHONE_RE = re.compile(r"^[0-9+()\s-]{7,24}$")
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]?\s?[0-9][A-Z]{2}$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

LIMITS = {
    "full_name": 100,
    "phone": 24,
    "email": 200,
    "service_type": 40,
    "property_address": 250,
    "postcode": 10,
    "job_description": 2000,
}

REQUIRED = (
    "full_name",
    "phone",
    "email",
    "service_type",
    "property_address",
    "postcode",
    "job_description",
    "requested_date",
    "requested_time",
)


class ValidationError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message

    def as_dict(self) -> dict:
        return {"error": "validation_failed", "field": self.field, "message": self.message}


@dataclass(frozen=True)
class BookingRequest:
    full_name: str
    phone: str
    email: str
    service_type: str
    property_address: str
    postcode: str
    job_description: str
    requested_date: date
    requested_time: str

    def as_public_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "phone": self.phone,
            "email": self.email,
            "service_type": self.service_type,
            "property_address": self.property_address,
            "postcode": self.postcode,
            "job_description": self.job_description,
            "requested_date": self.requested_date.isoformat(),
            "requested_time": self.requested_time,
        }


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        raise ValidationError("input", "Unexpected value type")
    text = str(value).strip()
    return text


def _require_text(payload: dict, field: str) -> str:
    value = _clean(payload.get(field))
    if not value:
        raise ValidationError(field, "This field is required")
    limit = LIMITS.get(field)
    if limit and len(value) > limit:
        raise ValidationError(field, f"Must be {limit} characters or fewer")
    return value


def validate_booking(payload: object, allowed_services: tuple[str, ...]) -> BookingRequest:
    if not isinstance(payload, dict):
        raise ValidationError("body", "Expected a JSON object")

    full_name = _require_text(payload, "full_name")
    phone = _require_text(payload, "phone")
    email = _require_text(payload, "email")
    service_type = _require_text(payload, "service_type")
    property_address = _require_text(payload, "property_address")
    postcode = _require_text(payload, "postcode")
    job_description = _require_text(payload, "job_description")
    raw_date = _require_text(payload, "requested_date")
    raw_time = _require_text(payload, "requested_time")

    if not EMAIL_RE.match(email):
        raise ValidationError("email", "Enter a valid email address")

    if not PHONE_RE.match(phone):
        raise ValidationError("phone", "Enter a valid phone number")

    normalised_postcode = postcode.upper().strip()
    if not POSTCODE_RE.match(normalised_postcode):
        raise ValidationError("postcode", "Enter a valid UK postcode")

    if service_type not in allowed_services:
        raise ValidationError("service_type", "Choose a service from the list")

    if not DATE_RE.match(raw_date):
        raise ValidationError("requested_date", "Use the format YYYY-MM-DD")
    try:
        requested = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValidationError("requested_date", "That date does not exist") from exc

    if not TIME_RE.match(raw_time):
        raise ValidationError("requested_time", "Use a 24-hour time such as 09:30")

    honeypot = _clean(payload.get("website"))
    if honeypot:
        raise ValidationError("website", "Rejected")

    return BookingRequest(
        full_name=" ".join(full_name.split())[:100],
        phone=phone,
        email=email.lower()[:200],
        service_type=service_type,
        property_address=property_address,
        postcode=normalised_postcode,
        job_description=job_description,
        requested_date=requested,
        requested_time=raw_time,
    )


__all__ = ["BookingRequest", "LIMITS", "REQUIRED", "ValidationError", "validate_booking"]