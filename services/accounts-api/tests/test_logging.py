import json
import logging
import sys

from app.logging_config import JsonFormatter


def test_formatter_emits_json_with_extra_fields():
    record = logging.makeLogRecord(
        {
            "name": "test",
            "levelname": "INFO",
            "msg": "hello %s",
            "args": ("world",),
            "account_id": "abc",
        }
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["service"] == "accounts-api"
    assert entry["account_id"] == "abc"
    assert "timestamp" in entry


def test_formatter_puts_exception_in_one_field():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in entry["exception"]


def test_account_created_log_has_id_but_no_personal_data(client, caplog):
    caplog.set_level(logging.INFO)
    client.post("/accounts", json={"owner_name": "Ali Khan", "initial_balance": "500"})
    created = [r for r in caplog.records if r.getMessage() == "account created"]
    assert len(created) == 1
    assert hasattr(created[0], "account_id")
    formatter = JsonFormatter()
    assert all("Ali Khan" not in formatter.format(r) for r in caplog.records)


def test_probes_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/healthz")
    assert not [r for r in caplog.records if r.getMessage() == "request"]
