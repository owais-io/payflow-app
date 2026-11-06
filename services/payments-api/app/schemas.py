from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentCreate(BaseModel):
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class Payment(BaseModel):
    id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal
    currency: str
    status: Literal["completed"]
    created_at: datetime
