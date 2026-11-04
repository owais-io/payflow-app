from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner_name: str = Field(min_length=1, max_length=100)
    initial_balance: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)


class Account(BaseModel):
    id: UUID
    owner_name: str
    balance: Decimal
    currency: str
    created_at: datetime


class Balance(BaseModel):
    account_id: UUID
    balance: Decimal
    currency: str
