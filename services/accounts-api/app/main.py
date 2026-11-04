from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status

from app import health, models  # noqa: F401  (models registers the table with Base)
from app.db import Base, get_engine
from app.schemas import Account, AccountCreate, Balance
from app.store import AccountStore, get_store


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Temporary: creates missing tables at startup.
    # Replaced by a proper migration step in Task 3.2.5.
    Base.metadata.create_all(get_engine())
    yield


app = FastAPI(title="accounts-api", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)

Store = Annotated[AccountStore, Depends(get_store)]


def _get_or_404(store: AccountStore, account_id: UUID) -> Account:
    account = store.get(account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


@app.post("/accounts", response_model=Account, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate, store: Store) -> Account:
    return store.create(body.owner_name, body.initial_balance)


@app.get("/accounts/{account_id}", response_model=Account)
def get_account(account_id: UUID, store: Store) -> Account:
    return _get_or_404(store, account_id)


@app.get("/accounts/{account_id}/balance", response_model=Balance)
def get_balance(account_id: UUID, store: Store) -> Balance:
    account = _get_or_404(store, account_id)
    return Balance(account_id=account.id, balance=account.balance, currency=account.currency)
