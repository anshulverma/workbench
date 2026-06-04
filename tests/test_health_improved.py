# tests/test_health_improved.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from workbench.api.health import router
from fastapi import FastAPI


def _make_app(stores_healthy=True, connections=None):
    app = FastAPI()
    app.include_router(router)

    stores = MagicMock()
    if stores_healthy:
        stores.items.pool.fetchval = AsyncMock(return_value=1)
        stores.ingestion_queue.get_depth = AsyncMock(return_value=3)
        stores.triage.get_pending = AsyncMock(return_value=[])
        stores.ingestion_queue.get_dead_letters = AsyncMock(return_value=[])
    else:
        stores.items.pool.fetchval = AsyncMock(side_effect=Exception("PG down"))

    app.state.stores = stores
    app.state.connections = connections or {}
    app.state.llm = MagicMock()
    app.state.memory = MagicMock()
    app.state.messenger = None
    return app


def test_health_returns_200_when_healthy():
    app = _make_app(stores_healthy=True)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "components" in data


def test_health_returns_503_when_pg_down():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["components"]["storage"]["status"] == "unhealthy"


def test_health_live_always_200():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200


def test_health_ready_503_when_pg_down():
    app = _make_app(stores_healthy=False)
    client = TestClient(app)
    resp = client.get("/health/ready")
    assert resp.status_code == 503


def test_health_includes_connection_status():
    conn = MagicMock()
    conn.is_healthy.return_value = False
    app = _make_app(stores_healthy=True, connections={"google": conn})
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200  # connection is non-critical
    data = resp.json()
    assert data["components"]["connections"]["google"]["status"] == "unhealthy"
