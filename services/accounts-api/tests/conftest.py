from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import InMemoryAccountStore, get_store


@pytest.fixture
def store() -> InMemoryAccountStore:
    return InMemoryAccountStore()


@pytest.fixture
def client(store: InMemoryAccountStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    # No `with` block: the lifespan hook (create_all) doesn't run, so no database is needed.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def account(client: TestClient) -> dict:
    resp = client.post("/accounts", json={"owner_name": "Ali Khan", "initial_balance": "1000"})
    assert resp.status_code == 201
    return resp.json()
