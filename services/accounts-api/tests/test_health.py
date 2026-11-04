from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

from app import health


def _database_down(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))
    monkeypatch.setattr(health, "get_engine", lambda: engine)


def test_readyz_ready_when_database_up(client, monkeypatch):
    monkeypatch.setattr(health, "get_engine", lambda: MagicMock())
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "up"}


def test_readyz_unavailable_when_database_down(client, monkeypatch):
    _database_down(monkeypatch)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable", "database": "down"}


def test_healthz_ok_even_when_database_down(client, monkeypatch):
    _database_down(monkeypatch)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
