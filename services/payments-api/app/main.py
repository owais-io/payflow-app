from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.accounts_client import AccountsClient, AccountsUnavailable
from app.config import get_settings
from app.db import Base, get_engine, get_sessionmaker
from app.ledger import AccountNotFound, InsufficientFunds, transfer
from app.models import TransactionRow
from app.schemas import Payment, PaymentCreate


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Temporary: creates the transactions table at startup (only that table).
    # Replaced by a proper migration step in Task 3.2.5.
    Base.metadata.create_all(get_engine(), tables=[TransactionRow.__table__])
    settings = get_settings()
    with httpx.Client(
        base_url=settings.accounts_api_url,
        timeout=settings.accounts_api_timeout_seconds,
    ) as http:
        app.state.accounts = AccountsClient(http)
        yield


app = FastAPI(title="payments-api", version="0.1.0", lifespan=lifespan)


def get_accounts_client(request: Request) -> AccountsClient:
    return request.app.state.accounts


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


Accounts = Annotated[AccountsClient, Depends(get_accounts_client)]
DbSession = Annotated[Session, Depends(get_session)]


@app.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(body: PaymentCreate, accounts: Accounts, session: DbSession) -> Payment:
    if body.from_account_id == body.to_account_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "from_account_id and to_account_id must differ"
        )

    try:
        for account_id in (body.from_account_id, body.to_account_id):
            if not accounts.account_exists(account_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    except AccountsUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "accounts service unavailable"
        ) from None

    try:
        tx = transfer(session, body.from_account_id, body.to_account_id, body.amount)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {exc.args[0]} not found") from None
    except InsufficientFunds:
        raise HTTPException(status.HTTP_409_CONFLICT, "insufficient funds") from None

    return Payment(
        id=tx.id,
        from_account_id=tx.from_account_id,
        to_account_id=tx.to_account_id,
        amount=tx.amount,
        currency=tx.currency,
        status=tx.status,
        created_at=tx.created_at,
    )
