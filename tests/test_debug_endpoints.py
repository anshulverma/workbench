# tests/test_debug_endpoints.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from workbench.api.debug import router


def _make_app():
    app = FastAPI()
    app.include_router(router)

    stores = MagicMock()
    stores.items.pool.fetch = AsyncMock(return_value=[])
    stores.ingestion_queue.queue_depth = AsyncMock(return_value=0)
    stores.ingestion_queue.count_dead_letters = AsyncMock(return_value=0)
    stores.triage.get_pending = AsyncMock(return_value=[])

    app.state.stores = stores
    app.state.connections = {}
    app.state.sources = []
    app.state.config = MagicMock()
    app.state.config.model_dump.return_value = {
        "version": "0.3.0",
        "server": {"api_token": "SECRET"},
    }
    app.state.metrics = None
    return app


def test_debug_adapters():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/adapters")
    assert resp.status_code == 200
    assert "adapters" in resp.json()


def test_debug_connections():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/connections")
    assert resp.status_code == 200
    assert "connections" in resp.json()


def test_debug_config_redacts_secrets():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/debug/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "SECRET" not in str(data)
