from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.models import AccountRow
from app.schemas import Account

CENTS = Decimal("0.01")
CURRENCY = "PKR"


class AccountStore(Protocol):
    def create(self, owner_name: str, initial_balance: Decimal) -> Account: ...
    def get(self, account_id: UUID) -> Account | None: ...


class InMemoryAccountStore:
    """In-memory store for tests; production uses PostgresAccountStore."""

    def __init__(self) -> None:
        self._accounts: dict[UUID, Account] = {}

    def create(self, owner_name: str, initial_balance: Decimal) -> Account:
        account = Account(
            id=uuid4(),
            owner_name=owner_name,
            balance=initial_balance.quantize(CENTS),
            currency=CURRENCY,
            created_at=datetime.now(UTC),
        )
        self._accounts[account.id] = account
        return account

    def get(self, account_id: UUID) -> Account | None:
        return self._accounts.get(account_id)


class PostgresAccountStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, owner_name: str, initial_balance: Decimal) -> Account:
        row = AccountRow(owner_name=owner_name, balance=initial_balance.quantize(CENTS))
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return _to_schema(row)

    def get(self, account_id: UUID) -> Account | None:
        row = self._session.get(AccountRow, account_id)
        return _to_schema(row) if row else None


def _to_schema(row: AccountRow) -> Account:
    return Account(
        id=row.id,
        owner_name=row.owner_name,
        balance=row.balance,
        currency=row.currency,
        created_at=row.created_at,
    )


def get_store() -> Iterator[AccountStore]:
    with get_sessionmaker()() as session:
        yield PostgresAccountStore(session)
