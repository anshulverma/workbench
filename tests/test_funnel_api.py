"""Funnel API tests (Slice 3).

Covers GET/PATCH funnel order, PATCH stage toggle, GET funnel items,
and GET item funnel trace.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
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
# Funnel Order
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_funnel_order_empty(client):
    r = await client.get("/api/funnel/order")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_set_and_get_funnel_order(client):
    entries = [
        {"stage_id": "filter-1", "label": "Noise Filter", "enabled": True},
        {"stage_id": "enricher-1", "label": "Context Enrichment", "enabled": True},
        {"stage_id": "filter-2", "label": "Priority Filter", "enabled": False},
    ]
    r = await client.patch("/api/funnel/order", json={"entries": entries})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert data[0]["stage_id"] == "filter-1"
    assert data[1]["stage_id"] == "enricher-1"
    assert data[2]["stage_id"] == "filter-2"

    # Verify order preserved
    r = await client.get("/api/funnel/order")
    assert r.status_code == 200
    assert len(r.json()) == 3


# --------------------------------------------------------------------------- #
# Stage Toggle
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_toggle_stage(client):
    entries = [
        {"stage_id": "stage-a", "label": "Stage A", "enabled": True},
    ]
    await client.patch("/api/funnel/order", json={"entries": entries})

    r = await client.patch("/api/funnel/stages/stage-a", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # Verify toggle persisted
    r = await client.get("/api/funnel/order")
    stage = [s for s in r.json() if s["stage_id"] == "stage-a"]
    assert stage[0]["enabled"] is False


# --------------------------------------------------------------------------- #
# Funnel Items
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_funnel_items_filters_by_funnel_log(client, stores):
    # Item without funnel_log
    item_no_log = Item(
        source_type="github",
        source_id="funnel-no-log",
        summary="No funnel log",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item_no_log)

    # Item with funnel_log
    item_with_log = Item(
        source_type="github",
        source_id="funnel-with-log",
        summary="Has funnel log",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
        funnel_log=[{"stage": "filter", "action": "include"}],
    )
    await stores.items.save_item(item_with_log)

    r = await client.get("/api/funnel/items")
    assert r.status_code == 200
    results = r.json()
    ids = [i["id"] for i in results]
    assert item_with_log.id in ids
    assert item_no_log.id not in ids


# --------------------------------------------------------------------------- #
# Item Funnel Trace
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_item_funnel(client, stores):
    item = Item(
        source_type="github",
        source_id="funnel-trace-1",
        summary="Trace test",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P1,
        funnel_log=[{"stage": "filter", "action": "include", "confidence": 80}],
        verdict_action="include",
        verdict_priority="P1",
        verdict_confidence=80,
    )
    await stores.items.save_item(item)

    # Log a stage via funnel traces
    await stores.funnel_traces.log_stage(
        item.id, {"stage": "enrichment", "depth": "shallow"}
    )

    r = await client.get(f"/api/items/{item.id}/funnel")
    assert r.status_code == 200
    data = r.json()
    assert data["item_id"] == item.id
    assert len(data["funnel_log"]) == 1
    assert len(data["stages"]) == 1
    assert data["verdict"]["action"] == "include"
    assert data["verdict"]["confidence"] == 80


@pytest.mark.asyncio
async def test_get_item_funnel_not_found(client):
    r = await client.get("/api/items/nonexistent-id/funnel")
    assert r.status_code == 404
