"""Tests for identity admin endpoints in the memory service."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from memory.main import create_app
from memory.queue import PendingIngestionStore

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"


@pytest.fixture
async def store():
    s = PendingIngestionStore(TEST_DSN)
    await s.initialize()
    await s.pool.execute("DELETE FROM entity_identities")
    await s.pool.execute("DELETE FROM entities")
    yield s
    await s.close()


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("MEMORY_ADMIN_ENABLED", "true")


# --- Admin merge endpoint ---


@pytest.mark.asyncio
async def test_admin_merge_endpoint(store, admin_env):
    """POST /admin/identity/merge merges two entities."""
    # Set up two separate entities
    await store.upsert_entity("person", "github:alice", {"team": "infra"})
    await store.resolve_identity("person", "github:alice", {"team": "infra"})

    await store.upsert_entity("person", "email:alice@co.com", {"role": "lead"})
    await store.resolve_identity("person", "email:alice@co.com", {"role": "lead"})

    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/identity/merge",
            params={
                "entity_type": "person",
                "winner_id": "github:alice",
                "loser_id": "email:alice@co.com",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "merged"
    assert data["canonical"] == "github:alice"

    # Verify the merge happened in the store
    canonical = await store.get_canonical("person", "email:alice@co.com")
    assert canonical == "github:alice"


@pytest.mark.asyncio
async def test_admin_merge_noop(store, admin_env):
    """POST /admin/identity/merge returns noop when winner not found."""
    await store.upsert_entity("person", "email:alice@co.com", {"role": "lead"})
    await store.resolve_identity("person", "email:alice@co.com", {"role": "lead"})

    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/identity/merge",
            params={
                "entity_type": "person",
                "winner_id": "nonexistent",
                "loser_id": "email:alice@co.com",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "noop"


@pytest.mark.asyncio
async def test_admin_merge_requires_admin_enabled(store):
    """POST /admin/identity/merge returns 403 when admin is disabled."""
    os.environ.pop("MEMORY_ADMIN_ENABLED", None)
    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/identity/merge",
            params={
                "entity_type": "person",
                "winner_id": "a",
                "loser_id": "b",
            },
        )
    assert resp.status_code == 403


# --- Admin split endpoint ---


@pytest.mark.asyncio
async def test_admin_split_endpoint(store, admin_env):
    """POST /admin/identity/split detaches a source_id from its canonical."""
    await store.upsert_entity("person", "github:alice", {"email": "a@co.com"})
    await store.resolve_identity("person", "github:alice", {"email": "a@co.com"})
    await store.resolve_identity("person", "email:a@co.com", {"email": "a@co.com"})

    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/identity/split",
            params={
                "entity_type": "person",
                "source_id": "email:a@co.com",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "split"
    assert data["source_id"] == "email:a@co.com"

    # Verify the split happened
    canonical = await store.get_canonical("person", "email:a@co.com")
    assert canonical == "email:a@co.com"


@pytest.mark.asyncio
async def test_admin_split_requires_admin_enabled(store):
    """POST /admin/identity/split returns 403 when admin is disabled."""
    os.environ.pop("MEMORY_ADMIN_ENABLED", None)
    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/admin/identity/split",
            params={"entity_type": "person", "source_id": "x"},
        )
    assert resp.status_code == 403


# --- Admin list endpoint ---


@pytest.mark.asyncio
async def test_admin_list_identities_endpoint(store, admin_env):
    """GET /admin/identity/list returns all aliases for a canonical."""
    await store.upsert_entity("person", "github:alice", {"email": "a@co.com"})
    await store.resolve_identity("person", "github:alice", {"email": "a@co.com"})
    await store.resolve_identity("person", "email:a@co.com", {"email": "a@co.com"})

    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/identity/list",
            params={
                "entity_type": "person",
                "canonical_id": "github:alice",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["canonical_id"] == "github:alice"
    source_ids = {a["source_id"] for a in data["aliases"]}
    assert "github:alice" in source_ids
    assert "email:a@co.com" in source_ids
    assert data["total"] == len(data["aliases"])


@pytest.mark.asyncio
async def test_admin_list_requires_admin_enabled(store):
    """GET /admin/identity/list returns 403 when admin is disabled."""
    os.environ.pop("MEMORY_ADMIN_ENABLED", None)
    app = create_app()
    app.state.store = store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/identity/list",
            params={"entity_type": "person", "canonical_id": "x"},
        )
    assert resp.status_code == 403
