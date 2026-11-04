from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.accounts_client import AccountsClient, AccountsUnavailable
from app.config import get_settings
from app.schemas import Payment, PaymentCreate


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    with httpx.Client(
        base_url=settings.accounts_api_url,
        timeout=settings.accounts_api_timeout_seconds,
    ) as http:
        app.state.accounts = AccountsClient(http)
        yield


app = FastAPI(title="payments-api", version="0.1.0", lifespan=lifespan)

_payments: list[Payment] = []  # replaced by PostgreSQL in 1.3.2


def get_accounts_client(request: Request) -> AccountsClient:
    return request.app.state.accounts


@app.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentCreate,
    accounts: Annotated[AccountsClient, Depends(get_accounts_client)],
) -> Payment:
    try:
        for account_id in (body.from_account_id, body.to_account_id):
            if not accounts.account_exists(account_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    except AccountsUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "accounts service unavailable"
        ) from None

    payment = Payment(
        id=uuid4(), **body.model_dump(), status="completed", created_at=datetime.now(UTC)
    )
    _payments.append(payment)
    return payment
