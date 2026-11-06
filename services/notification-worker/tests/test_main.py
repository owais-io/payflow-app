import json
import logging
import os
import signal
import sys
import threading
import urllib.request

import fakeredis
import pytest
from pydantic import ValidationError

from app import main
from app.config import Settings, get_settings
from app.logging_config import JsonFormatter, configure_logging
from app.metrics import start_metrics_server

# --- config: fail fast ----------------------------------------------------------


def test_settings_need_redis_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("HOSTNAME", "pod-1")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_need_hostname(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("HOSTNAME", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_consumer_name_comes_from_hostname(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("HOSTNAME", "notification-worker-7d9f-abcde")
    settings = Settings()
    assert settings.consumer_name == "notification-worker-7d9f-abcde"
    assert settings.payments_stream == "payflow:payments"
    assert settings.consumer_group == "notification-workers"
    assert settings.metrics_port == 9100


# --- logging ------------------------------------------------------------------


def test_formatter_emits_json_with_service_name():
    record = logging.makeLogRecord(
        {"name": "test", "levelname": "INFO", "msg": "hello", "payment_id": "abc"}
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["service"] == "notification-worker"
    assert entry["payment_id"] == "abc"


def test_formatter_puts_exception_in_one_field():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in entry["exception"]


def test_configure_logging_installs_one_json_handler():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("debug")
        [handler] = root.handlers
        assert isinstance(handler.formatter, JsonFormatter)
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


# --- 1.4.3: metrics side port -------------------------------------------------------


def test_metrics_server_serves_notifications_counter():
    server = start_metrics_server(0)  # 0 = any free port
    try:
        url = f"http://127.0.0.1:{server.server_port}/metrics"
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode()
    finally:
        server.shutdown()
    assert "notifications_sent_total" in body
    assert 'events_invalid_total{reason="invalid_json"}' in body


# --- 1.4.2: SIGTERM -------------------------------------------------------------


@pytest.fixture
def restore_signals():
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for s, handler in saved.items():
        signal.signal(s, handler)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_sets_stop(restore_signals, sig, caplog):
    stop = threading.Event()
    main.install_signal_handlers(stop)
    caplog.set_level(logging.INFO)
    os.kill(os.getpid(), sig)
    assert stop.wait(timeout=1)
    assert any(r.getMessage() == "shutdown requested" for r in caplog.records)


def test_main_wires_everything_and_cleans_up(monkeypatch, restore_signals, caplog):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("HOSTNAME", "pod-1")
    monkeypatch.setenv("METRICS_PORT", "0")
    get_settings.cache_clear()
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main.redis.Redis, "from_url", lambda *a, **kw: fake)
    seen = {}

    def fake_run(self, stop):
        seen["consumer"] = self._consumer
        seen["stop"] = stop

    monkeypatch.setattr(main.Worker, "run", fake_run)
    # configure_logging replaces the root handlers, which would remove caplog's handler.
    monkeypatch.setattr(main.logging_config, "configure_logging", lambda level: None)
    caplog.set_level(logging.INFO)
    try:
        main.main()
    finally:
        get_settings.cache_clear()

    assert seen["consumer"] == "pod-1"
    messages = [r.getMessage() for r in caplog.records]
    assert "worker started" in messages
    assert messages[-1] == "worker stopped"
