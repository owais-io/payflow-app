"""Consume payment.completed from a Redis Stream consumer group (at-least-once).

The life of one event:
  XREADGROUP ">"  -> Redis hands the entry to this consumer and puts it in the
                     group's Pending Entries List (PEL)
  log + count     -> the "notification"
  XACK            -> removed from the PEL; done

If the worker dies between reading and XACK, the entry stays in the PEL:
  - same consumer name restarts (container restart in the same pod):
    recover_pending() re-reads its own PEL at startup
  - the pod is gone for good (new pod, new name): another worker takes it over
    with XAUTOCLAIM once it has been idle for claim_idle_ms
Either way the notification may be logged twice; the contract allows that.
"""

import logging
import threading
import time
from collections.abc import Callable

import redis

from app.events import InvalidEvent, parse_event
from app.metrics import EVENTS_INVALID, NOTIFICATIONS_SENT, REDIS_ERRORS

logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0

Entry = tuple[str, dict[str, str] | None]


class Worker:
    def __init__(
        self,
        client: redis.Redis,
        *,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int = 2_000,
        batch_size: int = 10,
        claim_idle_ms: int = 60_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # The client must be created with decode_responses=True (fields are str, not bytes).
        self._client = client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._claim_idle_ms = claim_idle_ms
        self._clock = clock
        self._next_claim_at = 0.0  # claim on the first poll
        self._ready = False  # group exists and own pending entries recovered

    # --- startup -----------------------------------------------------------

    def ensure_group(self) -> None:
        """Create the stream and group if missing. Safe to call any number of times.

        id="0": a brand-new group starts from the oldest entry still in the stream,
        so events published before the first worker ever ran are not skipped.
        """
        try:
            self._client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
            logger.info("consumer group created", extra={"group": self._group})
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def recover_pending(self) -> int:
        """Handle entries this consumer read earlier but never acked (it crashed)."""
        handled = 0
        last_id = "0"
        while True:
            # An ID instead of ">" means "my own pending entries after this ID".
            response = self._client.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: last_id},
                count=self._batch_size,
            )
            entries = response[0][1] if response else []
            if not entries:
                break
            for entry_id, fields in entries:
                self._handle(entry_id, fields)
                last_id = entry_id
                handled += 1
        if handled:
            logger.info("recovered own pending events", extra={"count": handled})
        return handled

    # --- steady state --------------------------------------------------------

    def claim_stale(self) -> int:
        """Take over entries another consumer left unacked for claim_idle_ms."""
        handled = 0
        start = "0-0"
        while True:
            result = self._client.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                min_idle_time=self._claim_idle_ms,
                start_id=start,
                count=self._batch_size,
            )
            start, entries = result[0], result[1]
            for entry_id, fields in entries:
                self._handle(entry_id, fields)
                handled += 1
            if start == "0-0":  # the whole PEL has been scanned
                break
        if handled:
            logger.info("claimed stale events", extra={"count": handled})
        return handled

    def poll_once(self) -> int:
        """One loop iteration: maybe claim stale entries, then wait for new ones."""
        handled = 0
        now = self._clock()
        if now >= self._next_claim_at:
            handled += self.claim_stale()
            self._next_claim_at = now + self._claim_idle_ms / 1000

        response = self._client.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: ">"},
            count=self._batch_size,
            block=self._block_ms,
        )
        for _stream, entries in response or []:
            for entry_id, fields in entries:
                self._handle(entry_id, fields)
                handled += 1
        return handled

    def run(self, stop: threading.Event) -> None:
        """Loop until `stop` is set. Redis outages are retried with backoff, never fatal.

        `stop` is checked between batches, so a batch already read is finished and
        acked before the loop exits. Worst case after stop: one block_ms wait.
        """
        backoff = INITIAL_BACKOFF_SECONDS
        while not stop.is_set():
            try:
                if not self._ready:
                    self.ensure_group()
                    self.recover_pending()
                    self._ready = True
                self.poll_once()
                backoff = INITIAL_BACKOFF_SECONDS
            except redis.ResponseError as exc:
                if "NOGROUP" not in str(exc):
                    raise
                # Redis lost the stream or group (restarted without persistence).
                logger.warning("consumer group missing, recreating", extra={"group": self._group})
                self._ready = False
            except redis.RedisError as exc:
                REDIS_ERRORS.inc()
                logger.warning(
                    "redis unavailable, retrying",
                    extra={"error": str(exc), "retry_in_seconds": backoff},
                )
                stop.wait(backoff)  # returns early if stop is set during the wait
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    # --- one entry -----------------------------------------------------------

    def _handle(self, entry_id: str, fields: dict[str, str] | None) -> None:
        try:
            event = parse_event(fields)
        except InvalidEvent as exc:
            # A bad entry will never parse, so retrying it would block the PEL forever.
            # Count it, log it, ack it. (A dead-letter stream would keep a copy; out of scope.)
            EVENTS_INVALID.labels(exc.reason).inc()
            logger.error(
                "invalid event dropped",
                extra={"entry_id": entry_id, "reason": exc.reason, "error": str(exc)},
            )
        else:
            logger.info(
                "notification sent",
                extra={
                    "entry_id": entry_id,
                    "event_id": str(event.event_id),
                    "payment_id": str(event.data.payment_id),
                    "from_account_id": str(event.data.from_account_id),
                    "to_account_id": str(event.data.to_account_id),
                    "amount": str(event.data.amount),
                    "currency": event.data.currency,
                },
            )
            NOTIFICATIONS_SENT.inc()
        # Ack only after logging: a crash before this line means redelivery, not loss.
        self._client.xack(self._stream, self._group, entry_id)
