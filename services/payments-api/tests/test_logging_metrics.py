import json
import logging
import sys

from prometheus_client import REGISTRY

from app.logging_config import JsonFormatter


def test_formatter_emits_json_with_service_name():
    record = logging.makeLogRecord(
        {"name": "test", "levelname": "INFO", "msg": "hello", "payment_id": "abc"}
    )
    entry = json.loads(JsonFormatter().format(record))
    assert entry["service"] == "payments-api"
    assert entry["payment_id"] == "abc"


def test_formatter_puts_exception_in_one_field():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in entry["exception"]


def test_rejection_is_logged_with_reason(client, two_accounts, caplog):
    a, _ = two_accounts
    caplog.set_level(logging.INFO)
    client.post("/payments", json={"from_account_id": a, "to_account_id": a, "amount": "1.00"})
    [record] = [r for r in caplog.records if r.getMessage() == "payment rejected"]
    assert record.reason == "same_account"
    assert record.status == 400


def test_probes_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/healthz")
    assert not [r for r in caplog.records if r.getMessage() == "request"]


def test_payments_are_labelled_by_route_not_id(client, two_accounts):
    a, b = two_accounts
    labels = {"method": "POST", "path": "/payments", "status": "201"}
    before = REGISTRY.get_sample_value("http_requests_total", labels) or 0.0
    client.post("/payments", json={"from_account_id": a, "to_account_id": b, "amount": "1.00"})
    assert REGISTRY.get_sample_value("http_requests_total", labels) == before + 1


def test_failure_reasons_exist_before_any_failure(client):
    text = client.get("/metrics").text
    for reason in (
        "same_account",
        "account_not_found",
        "accounts_unavailable",
        "insufficient_funds",
    ):
        assert f'payments_failed_total{{reason="{reason}"}}' in text
