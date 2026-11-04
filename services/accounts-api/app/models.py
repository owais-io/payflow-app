import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, CheckConstraint, DateTime, Numeric, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_name: Mapped[str] = mapped_column(String(100), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="PKR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
