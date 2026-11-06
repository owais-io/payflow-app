from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import metrics
from app.accounts_client import AccountsClient, AccountsUnavailable
from app.config import get_settings
from app.db import Base, get_engine, get_sessionmaker
from app.events import EventPublisher
from app.ledger import AccountNotFound, InsufficientFunds, transfer
from app.models import TransactionRow
from app.schemas import Payment, PaymentCreate


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Temporary: creates the transactions table at startup (only that table).
    # Replaced by a proper migration step in Task 3.2.5.
    Base.metadata.create_all(get_engine(), tables=[TransactionRow.__table__])
    settings = get_settings()
    redis_client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_timeout_seconds,
        socket_timeout=settings.redis_timeout_seconds,
    )
    app.state.events = EventPublisher(redis_client, settings.payments_stream)
    with httpx.Client(
        base_url=settings.accounts_api_url,
        timeout=settings.accounts_api_timeout_seconds,
    ) as http:
        app.state.accounts = AccountsClient(http)
        yield
    redis_client.close()


app = FastAPI(title="payments-api", version="0.1.0", lifespan=lifespan)
app.include_router(metrics.router)


def get_accounts_client(request: Request) -> AccountsClient:
    return request.app.state.accounts


def get_events(request: Request) -> EventPublisher:
    return request.app.state.events


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


Accounts = Annotated[AccountsClient, Depends(get_accounts_client)]
Events = Annotated[EventPublisher, Depends(get_events)]
DbSession = Annotated[Session, Depends(get_session)]


@app.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentCreate, accounts: Accounts, events: Events, session: DbSession
) -> Payment:
    if body.from_account_id == body.to_account_id:
        metrics.PAYMENTS_FAILED.labels("same_account").inc()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "from_account_id and to_account_id must differ"
        )

    try:
        for account_id in (body.from_account_id, body.to_account_id):
            if not accounts.account_exists(account_id):
                metrics.PAYMENTS_FAILED.labels("account_not_found").inc()
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    except AccountsUnavailable:
        metrics.PAYMENTS_FAILED.labels("accounts_unavailable").inc()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "accounts service unavailable"
        ) from None

    try:
        tx = transfer(session, body.from_account_id, body.to_account_id, body.amount)
    except AccountNotFound as exc:
        metrics.PAYMENTS_FAILED.labels("account_not_found").inc()
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {exc.args[0]} not found") from None
    except InsufficientFunds:
        metrics.PAYMENTS_FAILED.labels("insufficient_funds").inc()
        raise HTTPException(status.HTTP_409_CONFLICT, "insufficient funds") from None

    metrics.PAYMENTS.inc()
    metrics.PAYMENT_AMOUNT.observe(float(tx.amount))

    # Only after the commit inside transfer(): a rolled-back payment never sends an event.
    events.publish_payment_completed(tx)

    return Payment(
        id=tx.id,
        from_account_id=tx.from_account_id,
        to_account_id=tx.to_account_id,
        amount=tx.amount,
        currency=tx.currency,
        status=tx.status,
        created_at=tx.created_at,
    )
