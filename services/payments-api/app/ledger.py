from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import TransactionRow


class AccountNotFound(Exception):
    pass


class InsufficientFunds(Exception):
    pass


# Locks both rows. ORDER BY id means every transfer locks in the same order
# (lower UUID first), so A->B and B->A running at once can't deadlock.
_LOCK_ACCOUNTS = text(
    "SELECT id, balance FROM accounts WHERE id IN (:a, :b) ORDER BY id FOR UPDATE"
)
_ADJUST_BALANCE = text("UPDATE accounts SET balance = balance + :delta WHERE id = :id")


def transfer(session: Session, from_id: UUID, to_id: UUID, amount: Decimal) -> TransactionRow:
    with session.begin():  # commits on success, rolls back on any exception
        rows = session.execute(_LOCK_ACCOUNTS, {"a": from_id, "b": to_id}).all()
        balances = {row.id: row.balance for row in rows}

        for account_id in (from_id, to_id):
            if account_id not in balances:
                raise AccountNotFound(account_id)
        if balances[from_id] < amount:
            raise InsufficientFunds(from_id)

        session.execute(_ADJUST_BALANCE, {"delta": -amount, "id": from_id})
        session.execute(_ADJUST_BALANCE, {"delta": amount, "id": to_id})
        tx = TransactionRow(from_account_id=from_id, to_account_id=to_id, amount=amount)
        session.add(tx)
        session.flush()  # sends the INSERT so PostgreSQL fills id, currency, status, created_at
        session.refresh(tx)
    return tx
