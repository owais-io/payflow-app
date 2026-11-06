import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import redis

from app.metrics import EVENTS_PUBLISH_FAILED
from app.models import TransactionRow

log = logging.getLogger("payments-api.events")

STREAM_MAXLEN = 10_000  # approximate cap so the stream can't fill Redis memory


def payment_completed_event(tx: TransactionRow) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": "payment.completed",
        "version": 1,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data": {
            "payment_id": str(tx.id),
            "from_account_id": str(tx.from_account_id),
            "to_account_id": str(tx.to_account_id),
            "amount": str(tx.amount),
            "currency": tx.currency,
        },
    }


class EventPublisher:
    def __init__(self, client: redis.Redis, stream: str) -> None:
        self._client = client
        self._stream = stream

    def publish_payment_completed(self, tx: TransactionRow) -> bool:
        """Best effort: never raises. Returns False if the event could not be published."""
        event = payment_completed_event(tx)
        try:
            self._client.xadd(
                self._stream,
                {"payload": json.dumps(event)},
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        except redis.RedisError:
            # The payment is already committed; losing the event is the documented
            # trade-off (no outbox). The counter makes the loss visible and alertable.
            EVENTS_PUBLISH_FAILED.inc()
            log.exception("failed to publish payment.completed for payment %s", tx.id)
            return False
        return True
