"""
API tests for the Workbench server.

These tests bypass the normal lifespan (which requires a real PostgreSQL and
external providers) and instead wire up app.state manually with the PG stores
from conftest and mock/stub providers.
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from workbench.models import (
    ExtractedItem, ItemCategory, RawItem, TriageCard, TriageOption,
)
from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 50)
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    return llm


@pytest_asyncio.fixture
async def app_with_state(stores, mock_llm):
    """Create a fresh FastAPI app with test-appropriate state.

    We patch get_config so the module-level create_app() can build an app
    without a real config file, then set up state manually.
    """
    from workbench.config import AppConfig, ServerConfig, StorageConfig

    test_config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://workbench:workbench@localhost:5432/workbench"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "test"},
        server=ServerConfig(api_token="dev-token-change-me"),
    )

    with patch("workbench.main.get_config", return_value=test_config):
        # Import create_app inside the patch so the module-level app is not affected
        from workbench.main import create_app
        test_app = create_app()

    # Wire up state manually (skip lifespan which needs real providers)
    test_app.state.config = test_config
    test_app.state.stores = stores
    test_app.state.memory = NoopMemoryLayer()
    test_app.state.llm = mock_llm
    test_app.state.enricher = StubEnricher()
    test_app.state.messenger = None
    test_app.state.queue_scorer = None
    test_app.state.sources = []
    test_app.state.pipeline = PipelineEngine(
        stores, NoopMemoryLayer(), mock_llm, StubEnricher()
    )

    yield test_app


@pytest_asyncio.fixture
async def client(app_with_state):
    transport = ASGITransport(app=app_with_state)
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
async def test_health_no_auth(client, app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_items_requires_auth(client, app_with_state):
    transport = ASGITransport(app=app_with_state)
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
