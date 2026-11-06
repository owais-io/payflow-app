import json
from decimal import Decimal

import pytest

from app.events import InvalidEvent, parse_event
from tests.conftest import make_event


def _fields(event) -> dict[str, str]:
    return {"payload": json.dumps(event)}


def test_parses_event_published_by_payments_api():
    raw = make_event()
    event = parse_event(_fields(raw))
    assert str(event.data.payment_id) == raw["data"]["payment_id"]
    assert event.data.amount == Decimal("250.00")
    assert event.data.currency == "PKR"


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        (None, "missing_payload"),
        ({}, "missing_payload"),
        ({"other": "x"}, "missing_payload"),
        ({"payload": "not json"}, "invalid_json"),
        ({"payload": "[1, 2]"}, "invalid_json"),
        (_fields(make_event(event_type="payment.refunded")), "unknown_type"),
        (_fields(make_event(version=2)), "unsupported_version"),
        (_fields(make_event(data={"payment_id": "not-a-uuid"})), "invalid_schema"),
    ],
)
def test_rejects_with_reason(fields, reason):
    with pytest.raises(InvalidEvent) as exc_info:
        parse_event(fields)
    assert exc_info.value.reason == reason
