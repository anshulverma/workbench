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
    EnricherConfig,
    EnrichmentTrace,
    FilterRule,
    Item,
    ItemCategory,
    ItemOrigin,
    LoopBackConfig,
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


# --------------------------------------------------------------------------- #
# Funnel facade — filter rules (the contract the UI funnel page consumes)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_funnel_filter_rules_returns_extended_shape(client, stores):
    rule = FilterRule(
        prompt="Drop CI passing-build noise",
        action="drop",
        sources=["github"],
        confidence=92,
        origin="learned",
        matched=14,
        order_index=0,
    )
    await stores.filter_rules.add_rule(rule)

    r = await client.get("/api/funnel/filter-rules")
    assert r.status_code == 200
    rows = r.json()
    row = [x for x in rows if x["id"] == rule.id][0]
    for key in (
        "id",
        "prompt",
        "action",
        "sources",
        "confidence",
        "origin",
        "matched",
        "enabled",
        "order_index",
    ):
        assert key in row, f"missing {key} in {row}"
    assert row["action"] == "drop"
    assert row["matched"] == 14
    assert row["sources"] == ["github"]


@pytest.mark.asyncio
async def test_funnel_create_filter_rule(client, stores):
    r = await client.post(
        "/api/funnel/filter-rules",
        json={
            "prompt": "Include diffs mentioning my team",
            "action": "include",
            "sources": ["github", "email"],
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["prompt"] == "Include diffs mentioning my team"
    assert created["action"] == "include"
    assert created["sources"] == ["github", "email"]

    listed = await client.get("/api/funnel/filter-rules")
    assert created["id"] in [x["id"] for x in listed.json()]


@pytest.mark.asyncio
async def test_funnel_delete_filter_rule(client, stores):
    rule = FilterRule(prompt="temp", action="drop")
    await stores.filter_rules.add_rule(rule)

    r = await client.delete(f"/api/funnel/filter-rules/{rule.id}")
    assert r.status_code == 200
    assert r.json() == {"status": "deleted"}

    listed = await client.get("/api/funnel/filter-rules")
    assert rule.id not in [x["id"] for x in listed.json()]


# --------------------------------------------------------------------------- #
# Funnel facade — enrichers (config mapped to the UI's Enricher view shape)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_funnel_enrichers_view_shape(client, stores):
    enricher = EnricherConfig(
        name="GitHub Metadata",
        stage="context",
        provider="github",
        config={
            "depth": "shallow",
            "adds": ["author", "files_changed"],
            "records": ["people", "repos"],
            "budget": {"max_calls": 1, "max_time_ms": 5000},
        },
    )
    await stores.enrichers.upsert_enricher(enricher)
    # Two traces for this stage -> enriched=2, avg_ms=(10+30)/2=20
    await stores.enrichment.log_trace(
        EnrichmentTrace(item_id="i1", depth="context", calls_made=1, time_ms=10)
    )
    await stores.enrichment.log_trace(
        EnrichmentTrace(item_id="i2", depth="context", calls_made=1, time_ms=30)
    )

    r = await client.get("/api/funnel/enrichers")
    assert r.status_code == 200
    row = [x for x in r.json() if x["id"] == enricher.id][0]
    assert row["type"] == "github"
    assert row["label"] == "GitHub Metadata"
    assert row["depth"] == "shallow"
    assert row["adds"] == ["author", "files_changed"]
    assert row["records"] == ["people", "repos"]
    assert row["budget"] == {"max_calls": 1, "max_time_ms": 5000}
    assert row["enriched"] == 2
    assert row["avg_ms"] == 20
    assert row["enabled"] is True


# --------------------------------------------------------------------------- #
# Funnel facade — loopbacks
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_funnel_loopbacks_view_shape(client, stores):
    lb = LoopBackConfig(
        name="Re-push stale",
        trigger="triaged >24h with no action",
        target_stage="triage",
        max_iterations=2,
        config={"condition": 'status == "triaged" && age_hours > 24'},
    )
    await stores.loopbacks.upsert_loopback(lb)

    r = await client.get("/api/funnel/loopbacks")
    assert r.status_code == 200
    row = [x for x in r.json() if x["id"] == lb.id][0]
    assert row["label"] == "Re-push stale"
    assert row["trigger"] == "triaged >24h with no action"
    assert row["condition"] == 'status == "triaged" && age_hours > 24'
    assert row["max_loops"] == 2
    assert row["enabled"] is True
    assert "looped" in row and "avg_loops" in row


# --------------------------------------------------------------------------- #
# Funnel facade — enrichment samples (keyed by enricher id)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_funnel_enrichment_samples_shape(client, stores):
    enricher = EnricherConfig(name="Ctx", stage="context", provider="github")
    await stores.enrichers.upsert_enricher(enricher)
    item = Item(
        source_type="github",
        source_id="sample-item",
        summary="PR #42: Fix login bug",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)
    await stores.enrichment.log_trace(
        EnrichmentTrace(
            item_id=item.id,
            depth="context",
            calls_made=1,
            time_ms=12,
            context_retrieved={"author": "alice", "files_changed": 3},
        )
    )

    r = await client.get("/api/funnel/enrichment-samples")
    assert r.status_code == 200
    data = r.json()
    assert enricher.id in data
    sample = data[enricher.id][0]
    assert sample["id"] == item.id
    assert sample["summary"] == "PR #42: Fix login bug"
    assert sample["context"]["author"] == "alice"


# --------------------------------------------------------------------------- #
# Funnel facade — item detail + list mapped to the UI FunnelItem shape
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_funnel_item_detail_shape(client, stores):
    item = Item(
        source_type="github",
        source_id="funnel-detail",
        summary="PR #7",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P1,
        funnel_log=[
            {"stage": "fr_01", "action": "include", "confidence": 88, "reason": "ok"}
        ],
        verdict_action="include",
        verdict_priority="P1",
        verdict_confidence=88,
    )
    await stores.items.save_item(item)

    r = await client.get(f"/api/funnel/items/{item.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == item.id
    assert data["summary"] == "PR #7"
    assert data["source"] == "github"
    assert data["verdict"]["decision"] == "triaged"
    assert data["verdict"]["priority"] == "P1"
    assert len(data["stages"]) == 1
    assert data["stages"][0]["outcome"] == "include"
    assert data["stages"][0]["confidence"] == 88


@pytest.mark.asyncio
async def test_funnel_item_detail_not_found(client):
    r = await client.get("/api/funnel/items/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_funnel_items_list_uses_funnel_item_shape(client, stores):
    item = Item(
        source_type="email",
        source_id="funnel-list",
        summary="Listed",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
        funnel_log=[{"stage": "fr_x", "action": "drop"}],
        verdict_action="drop",
    )
    await stores.items.save_item(item)

    r = await client.get("/api/funnel/items")
    assert r.status_code == 200
    row = [x for x in r.json() if x["id"] == item.id][0]
    assert row["source"] == "email"
    assert row["verdict"]["decision"] == "dropped"
    assert isinstance(row["stages"], list)


# --------------------------------------------------------------------------- #
# Funnel facade — POST stage toggle (UI uses POST .../toggle, not PATCH)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_toggle_stage_post(client):
    await client.patch(
        "/api/funnel/order",
        json={"entries": [{"stage_id": "stage-z", "label": "Z", "enabled": True}]},
    )

    r = await client.post("/api/funnel/stages/stage-z/toggle", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    order = await client.get("/api/funnel/order")
    stage = [s for s in order.json() if s["stage_id"] == "stage-z"][0]
    assert stage["enabled"] is False
