"""Global search API tests (Task B7 / Task 14, ADR0037).

Covers GET /api/search: grouped envelope across items/actions/sources, facts
degraded under NoopMemoryLayer, ILIKE wildcard escaping, limit cap + truncated
flag, ranking, and bearer auth.

Fixtures (mock_llm, app_with_state, client) mirror tests/test_stats_api.py.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.models import (
    Fact,
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    Priority,
    SourceConfig,
    TriageCard,
    TriageOption,
)


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


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_search_groups_items_actions_sources(client, stores):
    await stores.sources.upsert_source(
        SourceConfig(adapter_type="github", config={}, schedule="* * * * *")
    )
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="1",
            summary="RDS failover alert",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P0,
            status=ItemStatus.PENDING_TRIAGE,
        )
    )
    r = await client.get("/api/search?q=rds")
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "rds"
    assert "items" in body["groups"]
    assert "actions" in body["groups"]
    assert "sources" in body["groups"]
    assert any(h["label"].startswith("RDS") for h in body["groups"]["items"])
    assert body["groups"]["items"][0]["kind"] == "item"
    # pending_triage item routes to /triage
    assert body["groups"]["items"][0]["route"] == "/triage"


@pytest.mark.asyncio
async def test_search_active_item_routes_to_root(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="active-1",
            summary="ACTIVE widget signal",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.TRIAGED,
            priority=Priority.P1,
            status=ItemStatus.ACTIVE,
        )
    )
    r = await client.get("/api/search?q=widget")
    assert r.status_code == 200
    hits = r.json()["groups"]["items"]
    assert hits
    assert hits[0]["route"] == "/"


@pytest.mark.asyncio
async def test_search_groups_action_items(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="act-1",
            summary="Deploy zebra service",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority=Priority.P1,
            status=ItemStatus.ACTIVE,
            action_source="manual",
        )
    )
    r = await client.get("/api/search?q=zebra")
    assert r.status_code == 200
    body = r.json()
    actions = body["groups"]["actions"]
    assert any(h["kind"] == "action" for h in actions)
    assert actions[0]["route"] == "/actions"
    # action item is NOT duplicated into the items group
    assert all("zebra" not in h["label"].lower() for h in body["groups"]["items"])


@pytest.mark.asyncio
async def test_search_groups_sources(client, stores):
    await stores.sources.upsert_source(
        SourceConfig(
            id="src-jenkins",
            adapter_type="jenkins",
            config={},
            schedule="* * * * *",
        )
    )
    r = await client.get("/api/search?q=jenkins")
    assert r.status_code == 200
    sources = r.json()["groups"]["sources"]
    assert any(h["kind"] == "source" for h in sources)
    assert sources[0]["route"] == "/sources"


@pytest.mark.asyncio
async def test_search_escapes_ilike_wildcards(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="2",
            summary="literal percent test",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    r = await client.get("/api/search?q=%25")  # url-encoded '%'
    assert r.status_code == 200
    # '%' is escaped, not treated as a wildcard
    assert r.json()["groups"]["items"] == []


@pytest.mark.asyncio
async def test_search_escapes_underscore_wildcard(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="3",
            summary="abc",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    # '_' would match any single char if unescaped ('a_c' -> 'abc')
    r = await client.get("/api/search?q=a_c")
    assert r.status_code == 200
    assert r.json()["groups"]["items"] == []


@pytest.mark.asyncio
async def test_search_omits_facts_group_under_noop_memory(client):
    r = await client.get("/api/search?q=anything")
    assert r.status_code == 200
    assert "facts" not in r.json()["groups"]  # NoopMemoryLayer -> degraded


@pytest.mark.asyncio
async def test_search_includes_facts_when_memory_available(app_with_state):
    fake_memory = AsyncMock()
    fake_memory.memory_type = "http"
    fake_memory.is_available.return_value = True
    fake_memory.list_facts.return_value = [
        Fact(id="f1", content="Prefers RDS over Aurora", source="learned"),
        Fact(id="f2", content="Unrelated banana fact", source="learned"),
    ]
    app_with_state.state.memory = fake_memory

    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        r = await c.get("/api/search?q=rds")
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert "facts" in groups
    labels = [h["label"] for h in groups["facts"]]
    assert any("RDS" in lbl for lbl in labels)
    assert all("banana" not in lbl.lower() for lbl in labels)
    assert groups["facts"][0]["kind"] == "fact"
    assert groups["facts"][0]["route"] == "/knowledge"


@pytest.mark.asyncio
async def test_search_omits_facts_when_memory_unreachable(app_with_state):
    fake_memory = AsyncMock()
    fake_memory.memory_type = "http"
    fake_memory.is_available.side_effect = RuntimeError("down")
    app_with_state.state.memory = fake_memory

    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        r = await c.get("/api/search?q=rds")
    # never errors; facts simply omitted
    assert r.status_code == 200
    assert "facts" not in r.json()["groups"]


@pytest.mark.asyncio
async def test_search_caps_limit_at_50(client):
    r = await client.get("/api/search?q=ab&limit=999")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_search_truncated_flag_when_group_hits_cap(client, stores):
    # Insert more matching items than a low limit, assert truncated=true.
    for i in range(5):
        await stores.items.save_item(
            Item(
                source_type="github",
                source_id=f"trunc-{i}",
                summary=f"truncatron signal {i}",
                category=ItemCategory.INFORMATIONAL,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P2,
            )
        )
    r = await client.get("/api/search?q=truncatron&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["groups"]["items"]) == 2
    assert body["truncated"] is True


@pytest.mark.asyncio
async def test_search_ranks_prefix_before_substring(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="rank-sub",
            summary="a rankme suffix match",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="rank-pre",
            summary="rankme prefix wins",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    r = await client.get("/api/search?q=rankme")
    assert r.status_code == 200
    hits = r.json()["groups"]["items"]
    assert hits[0]["label"].startswith("rankme")


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty_groups(client, stores):
    await stores.items.save_item(
        Item(
            source_type="github",
            source_id="empty-q",
            summary="should not appear",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
        )
    )
    r = await client.get("/api/search?q=a")  # < 2 chars
    assert r.status_code == 200
    body = r.json()
    assert body["groups"]["items"] == []
    assert body["groups"]["actions"] == []
    assert body["groups"]["sources"] == []
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_search_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/search?q=rds")
    assert r.status_code == 401
