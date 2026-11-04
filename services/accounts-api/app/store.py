from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.schemas import Account

CENTS = Decimal("0.01")
CURRENCY = "PKR"


class InMemoryAccountStore:
    """Temporary store; replaced by PostgreSQL in 1.2.3."""

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


_store = InMemoryAccountStore()


def get_store() -> InMemoryAccountStore:
    return _store
