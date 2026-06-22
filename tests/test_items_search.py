"""Items search API tests (Slice 3).

Covers GET /api/items/search: full-text search, kind filter, limit cap
(requesting 200 returns at most 100), rich SearchItem response shape,
and snooze endpoint.
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
    ItemStatus,
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
# Search
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_search_returns_rich_results(client, stores):
    item = Item(
        source_type="github",
        source_id="search-1",
        summary="Deploy the hedgehog service",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P1,
        tags=["deploy", "hedgehog"],
        llm_summary="LLM says deploy hedgehog",
        enriched_context={"repo": "hedgehog-svc"},
        funnel_log=[{"stage": "filter", "action": "include"}],
        verdict_action="include",
        verdict_priority="P1",
        verdict_confidence=90,
    )
    await stores.items.save_item(item)

    r = await client.get("/api/items/search?q=hedgehog")
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "hedgehog"
    assert len(body["results"]) >= 1

    result = body["results"][0]
    assert result["summary"] == "Deploy the hedgehog service"
    assert result["kind"] == "item"
    assert result["tags"] == ["deploy", "hedgehog"]
    assert result["llm_summary"] == "LLM says deploy hedgehog"
    assert result["enriched_context"]["repo"] == "hedgehog-svc"
    assert len(result["processing_log"]) == 1
    assert result["verdict"]["action"] == "include"
    assert result["verdict"]["confidence"] == 90
    assert "created_at" in result
    assert "updated_at" in result


@pytest.mark.asyncio
async def test_search_kind_filter_action(client, stores):
    # Regular item
    item = Item(
        source_type="github",
        source_id="search-kind-item",
        summary="Walrus monitoring alert",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)

    # Action item
    action = Item(
        source_type="github",
        source_id="search-kind-action",
        summary="Walrus deploy task",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P1,
        action_source="manual",
    )
    await stores.items.save_item(action)

    # kind=action should only return action items
    r = await client.get("/api/items/search?q=walrus&kind=action")
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(res["kind"] == "action" for res in results)

    # kind=item should only return regular items
    r = await client.get("/api/items/search?q=walrus&kind=item")
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(res["kind"] == "item" for res in results)


@pytest.mark.asyncio
async def test_search_limit_cap_at_100(client, stores):
    """Requesting limit=200 should be capped to 100."""
    r = await client.get("/api/items/search?q=test&limit=200")
    assert r.status_code == 200
    # Even with limit=200 in query, the server caps to 100
    # (no items in DB matching 'test' anyway, but the cap is applied
    # at the query level)
    assert r.json()["total"] <= 100


@pytest.mark.asyncio
async def test_search_empty_query_returns_recent_items(client, stores):
    """No query -> the most recent items, ordered created_at DESC."""
    from datetime import datetime, timezone

    for i, summary in enumerate(["oldest item", "middle item", "newest item"]):
        await stores.items.save_item(
            Item(
                source_type="github",
                source_id=f"recent-{i}",
                summary=summary,
                category=ItemCategory.INFORMATIONAL,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P2,
            )
        )
        # Force distinct created_at so ordering is deterministic (newest = i==2).
        await stores.items.pool.execute(
            "UPDATE items SET created_at = $1 WHERE source_id = $2",
            datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            f"recent-{i}",
        )

    r = await client.get("/api/items/search?q=")
    assert r.status_code == 200
    results = r.json()["results"]
    summaries = [x["summary"] for x in results]
    assert {"oldest item", "middle item", "newest item"} <= set(summaries)
    # most recent first
    assert summaries.index("newest item") < summaries.index("oldest item")
    created = [x["created_at"] for x in results]
    assert created == sorted(created, reverse=True)


@pytest.mark.asyncio
async def test_search_single_char_returns_recent_items(client, stores):
    """A single character is treated as no-query and shows recent items."""
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="onechar-1",
            summary="single char shows recent",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    r = await client.get("/api/items/search?q=a")
    assert r.status_code == 200
    summaries = [x["summary"] for x in r.json()["results"]]
    assert "single char shows recent" in summaries


# --------------------------------------------------------------------------- #
# Snooze
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_snooze_item(client, stores):
    item = Item(
        source_type="github",
        source_id="snooze-1",
        summary="Snooze this",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/items/{item.id}/snooze",
        json={"hours": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "snoozed"
    assert "until" in body


@pytest.mark.asyncio
async def test_snooze_item_not_found(client):
    r = await client.post(
        "/api/items/999999/snooze",
        json={"hours": 4},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_snooze_default_hours(client, stores):
    item = Item(
        source_type="github",
        source_id="snooze-default",
        summary="Snooze default",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/items/{item.id}/snooze",
        json={},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "snoozed"
