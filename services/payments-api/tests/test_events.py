import json
from decimal import Decimal
from uuid import uuid4

import fakeredis
import redis

from app.events import STREAM_MAXLEN, EventPublisher, payment_completed_event
from app.models import TransactionRow


def _tx() -> TransactionRow:
    return TransactionRow(
        id=uuid4(),
        from_account_id=uuid4(),
        to_account_id=uuid4(),
        amount=Decimal("250.00"),
        currency="PKR",
    )


def test_event_matches_design_doc_shape():
    tx = _tx()
    event = payment_completed_event(tx)
    assert set(event) == {"event_id", "event_type", "version", "occurred_at", "data"}
    assert event["event_type"] == "payment.completed"
    assert event["version"] == 1
    assert event["occurred_at"].endswith("Z")
    assert event["data"] == {
        "payment_id": str(tx.id),
        "from_account_id": str(tx.from_account_id),
        "to_account_id": str(tx.to_account_id),
        "amount": "250.00",
        "currency": "PKR",
    }


def test_each_event_gets_its_own_id():
    tx = _tx()
    assert payment_completed_event(tx)["event_id"] != payment_completed_event(tx)["event_id"]


def test_publish_writes_one_payload_field():
    client = fakeredis.FakeRedis()
    assert EventPublisher(client, "s").publish_payment_completed(_tx()) is True
    [(_, fields)] = client.xrange("s")
    assert list(fields) == [b"payload"]
    json.loads(fields[b"payload"])  # valid JSON


def test_stream_is_capped():
    client = fakeredis.FakeRedis()
    publisher = EventPublisher(client, "s")
    for _ in range(STREAM_MAXLEN + 500):
        publisher.publish_payment_completed(_tx())
    # MAXLEN ~ trims approximately, so allow some slack above the cap
    assert client.xlen("s") < STREAM_MAXLEN + 500


def test_publish_never_raises_when_redis_is_down():
    dead = redis.Redis(port=1, socket_connect_timeout=0.2)  # nothing listens on port 1
    assert EventPublisher(dead, "s").publish_payment_completed(_tx()) is False
