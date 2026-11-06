import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, NoReturn

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import health, logging_config, metrics
from app.accounts_client import AccountsClient, AccountsUnavailable
from app.config import get_settings
from app.db import Base, get_engine, get_sessionmaker
from app.events import EventPublisher
from app.ledger import AccountNotFound, InsufficientFunds, transfer
from app.models import TransactionRow
from app.schemas import Payment, PaymentCreate

# Read directly from the environment (not Settings) so importing the app
# never requires the other variables; the tests in 1.3.6 rely on that.
logging_config.configure_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Temporary: creates the transactions table at startup (only that table).
    # Replaced by a proper migration step in Task 3.2.5.
    Base.metadata.create_all(get_engine(), tables=[TransactionRow.__table__])
    settings = get_settings()
    app.state.redis = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_timeout_seconds,
        socket_timeout=settings.redis_timeout_seconds,
    )
    app.state.events = EventPublisher(app.state.redis, settings.payments_stream)
    with httpx.Client(
        base_url=settings.accounts_api_url,
        timeout=settings.accounts_api_timeout_seconds,
    ) as http:
        app.state.accounts = AccountsClient(http)
        yield
    app.state.redis.close()


app = FastAPI(title="payments-api", version="0.1.0", lifespan=lifespan)
app.middleware("http")(metrics.track_requests)
app.include_router(health.router)
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


def _reject(reason: str, status_code: int, detail: str) -> NoReturn:
    """Count, log and raise in one place, so every rejection is handled the same way."""
    metrics.PAYMENTS_FAILED.labels(reason).inc()
    level = logging.WARNING if status_code >= 500 else logging.INFO
    logger.log(level, "payment rejected", extra={"reason": reason, "status": status_code})
    raise HTTPException(status_code, detail)


@app.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentCreate, accounts: Accounts, events: Events, session: DbSession
) -> Payment:
    if body.from_account_id == body.to_account_id:
        _reject(
            "same_account",
            status.HTTP_400_BAD_REQUEST,
            "from_account_id and to_account_id must differ",
        )

    try:
        for account_id in (body.from_account_id, body.to_account_id):
            if not accounts.account_exists(account_id):
                _reject(
                    "account_not_found",
                    status.HTTP_404_NOT_FOUND,
                    f"account {account_id} not found",
                )
    except AccountsUnavailable:
        _reject(
            "accounts_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "accounts service unavailable",
        )

    try:
        tx = transfer(session, body.from_account_id, body.to_account_id, body.amount)
    except AccountNotFound as exc:
        _reject("account_not_found", status.HTTP_404_NOT_FOUND, f"account {exc.args[0]} not found")
    except InsufficientFunds:
        _reject("insufficient_funds", status.HTTP_409_CONFLICT, "insufficient funds")

    metrics.PAYMENTS.inc()
    metrics.PAYMENT_AMOUNT.observe(float(tx.amount))
    logger.info("payment completed", extra={"payment_id": str(tx.id), "amount": str(tx.amount)})

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
