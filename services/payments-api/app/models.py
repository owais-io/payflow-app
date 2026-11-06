import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# accounts is owned by accounts-api. This stub exists only so the foreign keys
# below can resolve; payments-api never creates or alters this table.
accounts_ref = Table("accounts", Base.metadata, Column("id", Uuid, primary_key=True))


class TransactionRow(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "from_account_id <> to_account_id", name="ck_transactions_distinct_accounts"
        ),
        Index("ix_transactions_from_created", "from_account_id", text("created_at DESC")),
        Index("ix_transactions_to_created", "to_account_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="PKR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="completed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
