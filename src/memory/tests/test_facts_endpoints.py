"""Endpoint tests for fact curation (id / delete-tombstone / update).

The memory layer is mocked on app.state so these run without Neo4j/Graphiti
or Postgres.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from memory.main import create_app
from memory.models import Fact


def _client(layer):
    app = create_app()
    app.state.layer = layer
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_facts_returns_ids():
    layer = AsyncMock()
    layer.query_preferences = AsyncMock(
        return_value=[Fact(id="edge-1", content="User prefers auth diffs")]
    )

    async with _client(layer) as client:
        resp = await client.get("/facts")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["facts"][0]["id"] == "edge-1"
    assert data["facts"][0]["content"] == "User prefers auth diffs"


@pytest.mark.asyncio
async def test_delete_fact_returns_204():
    layer = AsyncMock()
    layer.delete_fact = AsyncMock()

    async with _client(layer) as client:
        resp = await client.delete("/facts/edge-1")

    assert resp.status_code == 204
    layer.delete_fact.assert_called_once_with("edge-1")


@pytest.mark.asyncio
async def test_delete_fact_not_found_returns_404():
    layer = AsyncMock()
    layer.delete_fact = AsyncMock(side_effect=KeyError("edge not found"))

    async with _client(layer) as client:
        resp = await client.delete("/facts/missing")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_fact_returns_200():
    layer = AsyncMock()
    layer.update_fact = AsyncMock()

    async with _client(layer) as client:
        resp = await client.patch("/facts/edge-1", json={"content": "new text"})

    assert resp.status_code == 200
    layer.update_fact.assert_called_once_with("edge-1", "new text")


@pytest.mark.asyncio
async def test_patch_fact_not_found_returns_404():
    layer = AsyncMock()
    layer.update_fact = AsyncMock(side_effect=KeyError("edge not found"))

    async with _client(layer) as client:
        resp = await client.patch("/facts/missing", json={"content": "x"})

    assert resp.status_code == 404
