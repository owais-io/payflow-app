from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.models import TransactionRow


def _row(from_id: UUID, to_id: UUID, minutes_ago: int) -> TransactionRow:
    return TransactionRow(
        id=uuid4(),
        from_account_id=from_id,
        to_account_id=to_id,
        amount=Decimal("10.00"),
        currency="PKR",
        status="completed",
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def test_returns_payments_in_the_order_the_ledger_gives(client, payment_history):
    a, b = uuid4(), uuid4()
    newest, oldest = _row(a, b, 1), _row(b, a, 5)
    payment_history.rows = [newest, oldest]
    resp = client.get("/payments", params={"account_id": str(a)})
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()] == [str(newest.id), str(oldest.id)]
    assert resp.json()[0]["amount"] == "10.00"


def test_unknown_account_returns_empty_list(client, payment_history):
    resp = client.get("/payments", params={"account_id": str(uuid4())})
    assert resp.status_code == 200
    assert resp.json() == []


def test_default_limit_is_50(client, payment_history):
    account_id = uuid4()
    client.get("/payments", params={"account_id": str(account_id)})
    assert payment_history.calls == [(account_id, 50)]


def test_limit_is_passed_through(client, payment_history):
    a, b = uuid4(), uuid4()
    payment_history.rows = [_row(a, b, i) for i in range(5)]
    resp = client.get("/payments", params={"account_id": str(a), "limit": 2})
    assert len(resp.json()) == 2


def test_missing_account_id_returns_422(client):
    assert client.get("/payments").status_code == 422


def test_malformed_account_id_returns_422(client):
    assert client.get("/payments", params={"account_id": "nope"}).status_code == 422


def test_limit_out_of_range_returns_422(client):
    account_id = str(uuid4())
    assert client.get("/payments", params={"account_id": account_id, "limit": 0}).status_code == 422
    assert (
        client.get("/payments", params={"account_id": account_id, "limit": 201}).status_code == 422
    )


def test_history_works_while_accounts_api_is_down(client, accounts, payment_history):
    accounts.unavailable = True
    resp = client.get("/payments", params={"account_id": str(uuid4())})
    assert resp.status_code == 200
