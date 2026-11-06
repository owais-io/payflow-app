import logging
import threading
from unittest.mock import MagicMock

import pytest
import redis
from prometheus_client import REGISTRY

from app.worker import INITIAL_BACKOFF_SECONDS, Worker
from tests.conftest import GROUP, STREAM, make_event, pending_count


def _sent_total() -> float:
    return REGISTRY.get_sample_value("notifications_sent_total") or 0.0


def _invalid_total(reason: str) -> float:
    return REGISTRY.get_sample_value("events_invalid_total", {"reason": reason}) or 0.0


def _notifications(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "notification sent"]


class StopAfter(threading.Event):
    """A stop event that sets itself after `n` loop checks, so run() can be tested."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self._left = n

    def is_set(self) -> bool:
        self._left -= 1
        if self._left < 0:
            self.set()
        return super().is_set()

    def wait(self, timeout: float | None = None) -> bool:  # no real sleeping in tests
        self.waited = timeout
        return super().is_set()


# --- group setup --------------------------------------------------------------


def test_ensure_group_creates_stream_and_group(redis_client, make_worker):
    make_worker().ensure_group()
    [group] = redis_client.xinfo_groups(STREAM)
    assert group["name"] == GROUP


def test_ensure_group_is_idempotent(redis_client, make_worker):
    worker = make_worker()
    worker.ensure_group()
    worker.ensure_group()  # BUSYGROUP is swallowed
    assert len(redis_client.xinfo_groups(STREAM)) == 1


def test_ensure_group_reraises_other_errors():
    client = MagicMock()
    client.xgroup_create.side_effect = redis.ResponseError("WRONGTYPE not a stream")
    with pytest.raises(redis.ResponseError):
        Worker(client, stream=STREAM, group=GROUP, consumer="a").ensure_group()


def test_new_group_reads_events_published_before_it_existed(publish, make_worker, caplog):
    publish()  # payments-api ran before any worker
    worker = make_worker()
    worker.ensure_group()
    caplog.set_level(logging.INFO)
    assert worker.poll_once() == 1
    assert len(_notifications(caplog)) == 1


# --- 1.4.1: consume, log, ack -------------------------------------------------


def test_event_is_logged_counted_and_acked(redis_client, publish, make_worker, caplog):
    worker = make_worker()
    worker.ensure_group()
    raw = make_event()
    publish(raw)
    before = _sent_total()
    caplog.set_level(logging.INFO)

    assert worker.poll_once() == 1

    [record] = _notifications(caplog)
    assert record.payment_id == raw["data"]["payment_id"]
    assert record.event_id == raw["event_id"]
    assert record.amount == "250.00"
    assert _sent_total() == before + 1
    assert pending_count(redis_client) == 0


def test_poll_with_nothing_new_returns_zero(make_worker):
    worker = make_worker()
    worker.ensure_group()
    assert worker.poll_once() == 0


def test_invalid_event_is_counted_and_acked_not_retried(redis_client, publish, make_worker, caplog):
    worker = make_worker()
    worker.ensure_group()
    publish(fields={"payload": "not json"})
    before = _invalid_total("invalid_json")
    caplog.set_level(logging.INFO)

    worker.poll_once()

    assert _invalid_total("invalid_json") == before + 1
    assert not _notifications(caplog)
    assert pending_count(redis_client) == 0


def test_invalid_reasons_exist_before_any_failure():
    for reason in ("missing_payload", "invalid_json", "unknown_type"):
        assert REGISTRY.get_sample_value("events_invalid_total", {"reason": reason}) is not None


def test_two_workers_in_one_group_share_the_events(publish, make_worker, caplog):
    a, b = make_worker("worker-a", batch_size=2), make_worker("worker-b", batch_size=2)
    a.ensure_group()
    for _ in range(4):
        publish()
    caplog.set_level(logging.INFO)

    assert a.poll_once() == 2
    assert b.poll_once() == 2
    payment_ids = [r.payment_id for r in _notifications(caplog)]
    assert len(set(payment_ids)) == 4  # each event handled once, by one worker


# --- at-least-once: crashes between read and ack -------------------------------


def _read_without_ack(client, consumer: str) -> None:
    """Simulate a worker that read an entry and crashed before XACK."""
    client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=10)


def test_restarted_consumer_recovers_its_own_pending(redis_client, publish, make_worker, caplog):
    worker = make_worker("worker-a")
    worker.ensure_group()
    publish()
    publish()
    _read_without_ack(redis_client, "worker-a")
    assert pending_count(redis_client) == 2
    caplog.set_level(logging.INFO)

    assert make_worker("worker-a", batch_size=1).recover_pending() == 2  # same name, restarted

    assert len(_notifications(caplog)) == 2
    assert pending_count(redis_client) == 0


def test_recover_pending_with_nothing_pending(make_worker):
    worker = make_worker()
    worker.ensure_group()
    assert worker.recover_pending() == 0


def test_stale_events_from_dead_pod_are_claimed(redis_client, publish, make_worker, caplog):
    make_worker().ensure_group()
    publish()
    _read_without_ack(redis_client, "dead-pod")
    caplog.set_level(logging.INFO)

    survivor = make_worker("worker-b", claim_idle_ms=0)
    assert survivor.claim_stale() == 1

    assert len(_notifications(caplog)) == 1
    assert pending_count(redis_client) == 0


def test_claim_waits_for_idle_time(redis_client, publish, make_worker):
    make_worker().ensure_group()
    publish()
    _read_without_ack(redis_client, "slow-but-alive")

    # The other consumer read it a moment ago; 60 s have not passed, so leave it alone.
    assert make_worker("worker-b", claim_idle_ms=60_000).claim_stale() == 0
    assert pending_count(redis_client) == 1


def test_poll_claims_on_first_call_then_on_schedule(make_worker):
    now = [100.0]
    worker = make_worker(claim_idle_ms=60_000, clock=lambda: now[0])
    worker.ensure_group()
    worker.claim_stale = MagicMock(return_value=0)

    worker.poll_once()
    worker.poll_once()
    assert worker.claim_stale.call_count == 1  # not again within 60 s
    now[0] += 60
    worker.poll_once()
    assert worker.claim_stale.call_count == 2


# --- run loop -----------------------------------------------------------------


def test_run_handles_events_until_stopped(redis_client, publish, make_worker, caplog):
    publish()
    caplog.set_level(logging.INFO)
    make_worker().run(StopAfter(2))
    assert len(_notifications(caplog)) == 1
    assert pending_count(redis_client) == 0


def test_run_exits_at_once_if_already_stopped(make_worker):
    stop = threading.Event()
    stop.set()
    worker = make_worker()
    worker.ensure_group = MagicMock()
    worker.run(stop)
    worker.ensure_group.assert_not_called()


def test_run_backs_off_when_redis_is_down():
    client = MagicMock()
    client.xgroup_create.side_effect = redis.ConnectionError("connection refused")
    before = REGISTRY.get_sample_value("redis_errors_total") or 0.0
    stop = StopAfter(3)

    Worker(client, stream=STREAM, group=GROUP, consumer="a").run(stop)

    assert REGISTRY.get_sample_value("redis_errors_total") == before + 3
    assert stop.waited == INITIAL_BACKOFF_SECONDS * 4  # 1 -> 2 -> 4, doubling


def test_run_recreates_group_after_redis_lost_it(redis_client, publish, make_worker, caplog):
    worker = make_worker()
    worker.ensure_group()
    worker._ready = True
    redis_client.flushall()  # Redis restarted without persistence: stream and group gone
    caplog.set_level(logging.INFO)

    worker.run(StopAfter(3))  # poll -> NOGROUP -> ensure_group -> poll

    assert any(r.getMessage() == "consumer group missing, recreating" for r in caplog.records)
    assert len(redis_client.xinfo_groups(STREAM)) == 1


def test_run_raises_unexpected_redis_errors():
    client = MagicMock()
    client.xgroup_create.side_effect = redis.ResponseError("WRONGTYPE not a stream")
    with pytest.raises(redis.ResponseError):
        Worker(client, stream=STREAM, group=GROUP, consumer="a").run(StopAfter(3))
