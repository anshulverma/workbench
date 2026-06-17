"""Enrichers API tests (Slice 3).

Covers GET enrichers list, GET single enricher, GET enricher samples.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import (
    EnricherConfig,
    EnrichmentTrace,
    TriageCard,
    TriageOption,
)


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

    with patch("workbench.runtime.app.get_config", return_value=test_config):
        from workbench.runtime.app import create_app

        test_app = create_app()

    from workbench.runtime.auth import BearerTokenMiddleware

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


# --------------------------------------------------------------------------- #
# Enrichers List
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_enrichers_empty(client):
    r = await client.get("/api/enrichers")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_enrichers(client, stores):
    enricher = EnricherConfig(
        name="Context Enricher",
        stage="context",
        provider="github",
    )
    await stores.enrichers.upsert_enricher(enricher)

    r = await client.get("/api/enrichers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Context Enricher"


@pytest.mark.asyncio
async def test_get_enricher(client, stores):
    enricher = EnricherConfig(
        name="Summary Enricher",
        stage="summary",
        provider="llm",
    )
    await stores.enrichers.upsert_enricher(enricher)

    r = await client.get(f"/api/enrichers/{enricher.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Summary Enricher"


@pytest.mark.asyncio
async def test_get_enricher_not_found(client):
    r = await client.get("/api/enrichers/999999")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Enricher Samples
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_enricher_samples(client, stores):
    enricher = EnricherConfig(
        name="Risk Enricher",
        stage="risk",
        provider="llm",
    )
    await stores.enrichers.upsert_enricher(enricher)

    # Log traces that match the enricher's stage
    trace = EnrichmentTrace(
        item_id=1,
        depth="risk",
        calls_made=2,
        time_ms=150,
        context_retrieved={"risk_score": 0.8},
    )
    await stores.enrichment.log_trace(trace)

    # Log a trace with different stage -- should NOT appear
    other_trace = EnrichmentTrace(
        item_id=2,
        depth="context",
        calls_made=1,
        time_ms=50,
    )
    await stores.enrichment.log_trace(other_trace)

    r = await client.get(f"/api/enrichers/{enricher.id}/samples")
    assert r.status_code == 200
    samples = r.json()
    assert len(samples) >= 1
    assert all(s["depth"] == "risk" for s in samples)


@pytest.mark.asyncio
async def test_get_enricher_samples_not_found(client):
    r = await client.get("/api/enrichers/999999/samples")
    assert r.status_code == 404
