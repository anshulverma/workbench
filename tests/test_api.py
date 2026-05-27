import os
import tempfile
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Override the sqlite path before importing the app so lifespan uses a temp DB
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["WORKBENCH_SQLITE_PATH"] = _tmp.name

from server.main import app  # noqa: E402
from server.storage.factory import create_stores  # noqa: E402
from server.config import Settings  # noqa: E402
from server.memory.noop import NoopMemoryLayer  # noqa: E402
from server.providers.llm.claude import ClaudeProvider  # noqa: E402
from server.providers.enrichment.stub import StubEnricher  # noqa: E402
from server.pipeline.engine import PipelineEngine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def setup_app_state():
    """Set up app state that would normally be created by the lifespan."""
    settings = Settings()
    app.state.stores = await create_stores(settings)
    app.state.memory = NoopMemoryLayer()
    app.state.llm = ClaudeProvider(
        settings.anthropic_api_key, settings.anthropic_base_url
    )
    app.state.enricher = StubEnricher()
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher
    )
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_no_auth(client):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_items_requires_auth(client):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/items")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_items_empty(client):
    r = await client.get("/api/items")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_filter_rules_crud(client):
    r = await client.post(
        "/api/filter-rules",
        json={"pattern": "CI bot comments", "action": "drop"},
    )
    assert r.status_code == 200
    r = await client.get("/api/filter-rules")
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_triage_pending_empty(client):
    r = await client.get("/api/triage/pending")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_config_get_patch(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

    r = await client.patch(
        "/api/config", json={"updates": {"theme": "dark"}}
    )
    assert r.status_code == 200
    assert r.json().get("theme") == "dark"


@pytest.mark.asyncio
async def test_memory_facts_empty(client):
    r = await client.get("/api/memory/facts")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_sources_crud(client):
    r = await client.post(
        "/api/sources",
        json={"adapter_type": "diff", "config": {"user_phid": "PHID-USER-123"}},
    )
    assert r.status_code == 200
    source_id = r.json()["id"]

    r = await client.get("/api/sources")
    assert len(r.json()) >= 1

    r = await client.patch(
        f"/api/sources/{source_id}",
        json={"enabled": False},
    )
    assert r.status_code == 200

    r = await client.delete(f"/api/sources/{source_id}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_job_not_found(client):
    r = await client.get("/api/jobs/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_item_not_found(client):
    r = await client.patch(
        "/api/items/nonexistent",
        json={"priority": "P0"},
    )
    assert r.status_code == 404
