from unittest.mock import MagicMock

import redis
from sqlalchemy.exc import OperationalError

from app import health, main


def _database(monkeypatch, up: bool) -> None:
    engine = MagicMock()
    if not up:
        engine.connect.side_effect = OperationalError(
            "SELECT 1", {}, Exception("connection refused")
        )
    monkeypatch.setattr(health, "get_engine", lambda: engine)


def _redis_down() -> None:
    dead = MagicMock()
    dead.ping.side_effect = redis.ConnectionError("connection refused")
    main.app.state.redis = dead


def test_ready_when_everything_up(client, monkeypatch):
    _database(monkeypatch, up=True)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "up", "redis": "up"}


def test_still_ready_when_redis_down(client, monkeypatch):
    """Redis is a soft dependency: reported, but the pod keeps taking traffic."""
    _database(monkeypatch, up=True)
    _redis_down()
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "up", "redis": "down"}


def test_unavailable_when_database_down(client, monkeypatch):
    """PostgreSQL is a hard dependency: no transfers possible, so 503."""
    _database(monkeypatch, up=False)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
    assert resp.json()["database"] == "down"


def test_healthz_ignores_dependencies(client, monkeypatch):
    _database(monkeypatch, up=False)
    _redis_down()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
