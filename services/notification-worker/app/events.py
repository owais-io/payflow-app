"""The payment.completed contract from docs/architecture.md, seen from the consumer side."""

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ValidationError

EVENT_TYPE = "payment.completed"
SUPPORTED_VERSIONS = {1}

# Why an entry could not be turned into a notification. Used as a metric label,
# so the set is fixed.
INVALID_REASONS = (
    "missing_payload",
    "invalid_json",
    "unknown_type",
    "unsupported_version",
    "invalid_schema",
)


class InvalidEvent(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class PaymentData(BaseModel):
    payment_id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal
    currency: str


class PaymentCompleted(BaseModel):
    event_id: UUID
    event_type: str
    version: int
    occurred_at: datetime
    data: PaymentData


def parse_event(fields: dict[str, str] | None) -> PaymentCompleted:
    """Turn one stream entry's fields into an event, or raise InvalidEvent with a reason."""
    if not fields or "payload" not in fields:
        raise InvalidEvent("missing_payload")

    try:
        raw = json.loads(fields["payload"])
    except json.JSONDecodeError as exc:
        raise InvalidEvent("invalid_json", str(exc)) from exc
    if not isinstance(raw, dict):
        raise InvalidEvent("invalid_json", "payload is not a JSON object")

    # Checked before full validation so a newer message shape is reported as
    # "unsupported_version", not as a confusing schema error.
    if raw.get("event_type") != EVENT_TYPE:
        raise InvalidEvent("unknown_type", str(raw.get("event_type")))
    if raw.get("version") not in SUPPORTED_VERSIONS:
        raise InvalidEvent("unsupported_version", str(raw.get("version")))

    try:
        return PaymentCompleted.model_validate(raw)
    except ValidationError as exc:
        raise InvalidEvent("invalid_schema", str(exc)) from exc
