from uuid import UUID

import pytest

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def test_create_account_returns_uuid_and_two_decimal_balance(account):
    UUID(account["id"])  # raises if not a valid UUID
    assert account["owner_name"] == "Ali Khan"
    assert account["balance"] == "1000.00"
    assert account["currency"] == "PKR"


def test_create_account_defaults_balance_to_zero(client):
    resp = client.post("/accounts", json={"owner_name": "Sara"})
    assert resp.status_code == 201
    assert resp.json()["balance"] == "0.00"


@pytest.mark.parametrize(
    "body",
    [
        {"owner_name": ""},
        {"owner_name": "   "},
        {"owner_name": "x" * 101},
        {"owner_name": "Ali", "initial_balance": "-5"},
        {"owner_name": "Ali", "initial_balance": "1.005"},
        {"initial_balance": "10"},
    ],
    ids=["empty-name", "blank-name", "name-too-long", "negative", "three-decimals", "no-name"],
)
def test_create_account_rejects_invalid_body(client, body):
    assert client.post("/accounts", json=body).status_code == 422


def test_get_account_returns_same_account(client, account):
    resp = client.get(f"/accounts/{account['id']}")
    assert resp.status_code == 200
    assert resp.json() == account


def test_get_balance(client, account):
    resp = client.get(f"/accounts/{account['id']}/balance")
    assert resp.status_code == 200
    assert resp.json() == {"account_id": account["id"], "balance": "1000.00", "currency": "PKR"}


@pytest.mark.parametrize("path", [f"/accounts/{UNKNOWN_ID}", f"/accounts/{UNKNOWN_ID}/balance"])
def test_unknown_account_returns_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "account not found"}


def test_malformed_id_returns_422(client):
    assert client.get("/accounts/not-a-uuid").status_code == 422
