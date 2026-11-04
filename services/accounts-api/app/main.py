from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status

from app.schemas import Account, AccountCreate, Balance
from app.store import InMemoryAccountStore, get_store

app = FastAPI(title="accounts-api", version="0.1.0")

Store = Annotated[InMemoryAccountStore, Depends(get_store)]


def _get_or_404(store: InMemoryAccountStore, account_id: UUID) -> Account:
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
