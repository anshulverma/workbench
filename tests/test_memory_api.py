"""Fact curation API tests (Task C2).

Fixtures (mock_llm, app_with_state, client) mirror tests/test_stats_api.py.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.models import Fact, TriageCard, TriageOption


# --------------------------------------------------------------------------- #
# Fixtures (file-local, mirrors test_stats_api.py)
# --------------------------------------------------------------------------- #
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
    from workbench.config import AppConfig, ServerConfig, StorageConfig

    test_config = AppConfig(
        storage=StorageConfig(
            postgres_dsn="postgres://workbench:workbench@localhost:5432/workbench"
        ),
        llm={
            "class": "workbench.providers.llm.anthropic.AnthropicLLM",
            "api_key": "test",
        },
        server=ServerConfig(api_token="dev-token-change-me"),
    )

    with patch("workbench.main.get_config", return_value=test_config):
        from workbench.main import create_app

        test_app = create_app()

    from workbench.auth import BearerTokenMiddleware

    for mw in test_app.user_middleware:
        if mw.cls is BearerTokenMiddleware:
            mw.kwargs["token"] = "dev-token-change-me"
    test_app.middleware_stack = test_app.build_middleware_stack()

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
async def test_facts_envelope_noop(client, app_with_state):
    r = await client.get("/api/memory/facts")
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is False
    assert data["memory_type"] == "noop"
    assert data["facts"] == []


@pytest.mark.asyncio
async def test_facts_envelope_available(client, app_with_state):
    mem = AsyncMock()
    mem.is_available.return_value = True
    mem.list_facts.return_value = [
        Fact(
            id="f1",
            content="user prioritizes blocked PRs",
            source="interaction",
            timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ),
    ]
    mem.memory_type = "zep"
    app_with_state.state.memory = mem
    r = await client.get("/api/memory/facts")
    data = r.json()
    assert data["available"] is True
    assert data["memory_type"] == "zep"
    assert data["facts"][0]["id"] == "f1"
    assert data["facts"][0]["timestamp"].startswith("2026-06-01")


@pytest.mark.asyncio
async def test_delete_fact_501_under_noop(client, app_with_state):
    r = await client.delete("/api/memory/facts/abc")
    assert r.status_code == 501
    assert r.json()["detail"] == "memory layer not configured"


@pytest.mark.asyncio
async def test_patch_fact_501_under_noop(client, app_with_state):
    r = await client.patch("/api/memory/facts/abc", json={"content": "new"})
    assert r.status_code == 501
    assert r.json()["detail"] == "memory layer not configured"


@pytest.mark.asyncio
async def test_delete_fact_success(client, app_with_state):
    mem = AsyncMock()
    mem.delete_fact.return_value = None
    app_with_state.state.memory = mem
    r = await client.delete("/api/memory/facts/f1")
    assert r.status_code == 200
    mem.delete_fact.assert_awaited_once_with("f1")


@pytest.mark.asyncio
async def test_patch_fact_success(client, app_with_state):
    mem = AsyncMock()
    mem.update_fact.return_value = None
    app_with_state.state.memory = mem
    r = await client.patch("/api/memory/facts/f1", json={"content": "edited"})
    assert r.status_code == 200
    mem.update_fact.assert_awaited_once_with("f1", "edited")
