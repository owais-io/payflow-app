from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts_client import AccountsUnavailable
from app.events import EventPublisher
from app.main import app, get_accounts_client, get_events, get_session
from app.models import TransactionRow

STREAM = "payflow:payments"


class FakeAccountsClient:
    """Stands in for accounts-api: knows a fixed set of account IDs."""

    def __init__(self) -> None:
        self.known: set[UUID] = set()
        self.unavailable = False

    def account_exists(self, account_id: UUID) -> bool:
        if self.unavailable:
            raise AccountsUnavailable("accounts-api is down (fake)")
        return account_id in self.known


class FakeLedger:
    """Replaces ledger.transfer(): no database, no locks.

    Real locking and rollback are covered by the race test (1.3.2) and the
    integration tests in Phase 7. Here we only test how main.py reacts.
    """

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[UUID, UUID, Decimal]] = []

    def __call__(self, session, from_id: UUID, to_id: UUID, amount: Decimal) -> TransactionRow:
        self.calls.append((from_id, to_id, amount))
        if self.error is not None:
            raise self.error
        return TransactionRow(
            id=uuid4(),
            from_account_id=from_id,
            to_account_id=to_id,
            amount=amount,
            currency="PKR",
            status="completed",
            created_at=datetime.now(UTC),
        )


class FakeHistory:
    """Replaces ledger.history(): returns whatever rows the test puts in."""

    def __init__(self) -> None:
        self.rows: list[TransactionRow] = []
        self.calls: list[tuple[UUID, int]] = []

    def __call__(self, session, account_id: UUID, limit: int) -> list[TransactionRow]:
        self.calls.append((account_id, limit))
        return self.rows[:limit]


@pytest.fixture
def accounts() -> FakeAccountsClient:
    return FakeAccountsClient()


@pytest.fixture
def ledger(monkeypatch) -> FakeLedger:
    fake = FakeLedger()
    monkeypatch.setattr(main, "transfer", fake)
    return fake


@pytest.fixture
def payment_history(monkeypatch) -> FakeHistory:
    fake = FakeHistory()
    monkeypatch.setattr(main, "history", fake)
    return fake


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


@pytest.fixture
def client(accounts, ledger, payment_history, redis_client) -> Iterator[TestClient]:
    app.dependency_overrides[get_accounts_client] = lambda: accounts
    app.dependency_overrides[get_events] = lambda: EventPublisher(redis_client, STREAM)
    app.dependency_overrides[get_session] = lambda: MagicMock()
    app.state.redis = redis_client  # used by /readyz
    # No `with` block: the lifespan hook doesn't run, so no database, Redis or accounts-api.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def two_accounts(accounts) -> tuple[str, str]:
    a, b = uuid4(), uuid4()
    accounts.known |= {a, b}
    return str(a), str(b)
