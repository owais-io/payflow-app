import json
from uuid import UUID, uuid4

import pytest
import redis
from prometheus_client import REGISTRY

from app.ledger import AccountNotFound, InsufficientFunds
from tests.conftest import STREAM


def _failed(reason: str) -> float:
    return REGISTRY.get_sample_value("payments_failed_total", {"reason": reason}) or 0.0


def _value(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


def _pay(client, from_id, to_id, amount="100.00"):
    return client.post(
        "/payments",
        json={"from_account_id": from_id, "to_account_id": to_id, "amount": amount},
    )


def test_transfer_returns_201_with_contract_fields(client, two_accounts):
    a, b = two_accounts
    resp = _pay(client, a, b, "250.00")
    assert resp.status_code == 201
    body = resp.json()
    UUID(body["id"])
    assert body["from_account_id"] == a
    assert body["to_account_id"] == b
    assert body["amount"] == "250.00"  # money is a string, never a float
    assert body["currency"] == "PKR"
    assert body["status"] == "completed"


def test_transfer_counts_success_and_amount(client, two_accounts):
    a, b = two_accounts
    before_total = _value("payments_total")
    before_sum = _value("payment_amount_sum")
    _pay(client, a, b, "250.00")
    assert _value("payments_total") == before_total + 1
    assert _value("payment_amount_sum") == before_sum + 250


def test_transfer_publishes_one_event(client, two_accounts, redis_client):
    a, b = two_accounts
    resp = _pay(client, a, b, "75.50")
    entries = redis_client.xrange(STREAM)
    assert len(entries) == 1
    event = json.loads(entries[0][1][b"payload"])
    assert event["event_type"] == "payment.completed"
    assert event["version"] == 1
    assert event["data"]["payment_id"] == resp.json()["id"]
    assert event["data"]["amount"] == "75.50"


def test_same_account_returns_400(client, two_accounts, ledger):
    a, _ = two_accounts
    before = _failed("same_account")
    resp = _pay(client, a, a)
    assert resp.status_code == 400
    assert _failed("same_account") == before + 1
    assert ledger.calls == []  # rejected before touching the database


def test_unknown_account_returns_404(client, two_accounts, ledger):
    a, _ = two_accounts
    before = _failed("account_not_found")
    resp = _pay(client, a, str(uuid4()))
    assert resp.status_code == 404
    assert _failed("account_not_found") == before + 1
    assert ledger.calls == []


def test_account_gone_before_lock_returns_404(client, two_accounts, ledger):
    """accounts-api said yes, but the row vanished before the lock: still a clean 404."""
    a, b = two_accounts
    ledger.error = AccountNotFound(UUID(b))
    resp = _pay(client, a, b)
    assert resp.status_code == 404
    assert b in resp.json()["detail"]


def test_insufficient_funds_returns_409_and_no_event(client, two_accounts, ledger, redis_client):
    a, b = two_accounts
    ledger.error = InsufficientFunds(UUID(a))
    before = _failed("insufficient_funds")
    resp = _pay(client, a, b, "999999.00")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "insufficient funds"}
    assert _failed("insufficient_funds") == before + 1
    assert redis_client.xlen(STREAM) == 0  # a failed transfer never announces itself


def test_accounts_api_down_returns_503(client, two_accounts, accounts, ledger):
    a, b = two_accounts
    accounts.unavailable = True
    before = _failed("accounts_unavailable")
    resp = _pay(client, a, b)
    assert resp.status_code == 503
    assert _failed("accounts_unavailable") == before + 1
    assert ledger.calls == []


def test_redis_down_still_returns_201(client, two_accounts, monkeypatch, redis_client):
    """The payment is committed, so losing the event must not fail the request."""
    a, b = two_accounts

    def broken_xadd(*args, **kwargs):
        raise redis.ConnectionError("redis is down (fake)")

    monkeypatch.setattr(redis_client, "xadd", broken_xadd)
    before = _value("events_publish_failed_total")
    resp = _pay(client, a, b)
    assert resp.status_code == 201
    assert _value("events_publish_failed_total") == before + 1


@pytest.mark.parametrize(
    "amount",
    ["0", "-5.00", "1.005", "abc", "10000000000.00"],
    ids=["zero", "negative", "three-decimals", "not-a-number", "too-many-digits"],
)
def test_invalid_amount_returns_422(client, two_accounts, ledger, amount):
    a, b = two_accounts
    assert _pay(client, a, b, amount).status_code == 422
    assert ledger.calls == []


def test_malformed_account_id_returns_422(client, two_accounts):
    a, _ = two_accounts
    assert _pay(client, a, "not-a-uuid").status_code == 422


def test_invalid_body_is_not_counted_as_failed_payment(client, two_accounts):
    """422 is a broken client, not a failed payment; only HTTP metrics see it."""
    a, b = two_accounts
    before = sum(
        _failed(r)
        for r in ("same_account", "account_not_found", "accounts_unavailable", "insufficient_funds")
    )
    _pay(client, a, b, "-1")
    after = sum(
        _failed(r)
        for r in ("same_account", "account_not_found", "accounts_unavailable", "insufficient_funds")
    )
    assert after == before
