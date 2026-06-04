import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.models import (
    Item, ItemCategory, ItemOrigin, ItemStatus, ItemUpdate, Priority,
    TriageCard, TriageOption,
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
    from workbench.config import AppConfig, ServerConfig, StorageConfig

    test_config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://workbench:workbench@localhost:5432/workbench"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "test"},
        server=ServerConfig(api_token="dev-token-change-me"),
    )

    with patch("workbench.main.get_config", return_value=test_config):
        from workbench.main import create_app
        test_app = create_app()

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
async def test_get_actions_empty(client):
    r = await client.get("/api/actions")
    assert r.status_code == 200
    data = r.json()
    assert data["categories"] == {}
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_actions_grouped(client, app_with_state):
    stores = app_with_state.state.stores
    item1 = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
        parent_item_id="parent-1",
    )
    item2 = Item(
        source_type="diff", source_id="d1",
        summary="Review RFC", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P1,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="review",
    )
    await stores.items.save_item(item1)
    await stores.items.save_item(item2)

    r = await client.get("/api/actions")
    assert r.status_code == 200
    data = r.json()
    assert "delegation" in data["categories"]
    assert "review" in data["categories"]
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_get_actions_filter_by_category(client, app_with_state):
    stores = app_with_state.state.stores
    item1 = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    item2 = Item(
        source_type="diff", source_id="d1",
        summary="Review RFC", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P1,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="review",
    )
    await stores.items.save_item(item1)
    await stores.items.save_item(item2)

    r = await client.get("/api/actions?category=delegation")
    assert r.status_code == 200
    data = r.json()
    assert "delegation" in data["categories"]
    assert "review" not in data["categories"]
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_mark_action_done(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(f"/api/actions/{item.id}/done")
    assert r.status_code == 200

    updated = await stores.items.get_item(item.id)
    assert updated.status == ItemStatus.DONE


@pytest.mark.asyncio
async def test_mark_action_done_logs_lifecycle(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    await client.post(f"/api/actions/{item.id}/done")

    entries = await stores.interactions.get_all()
    lifecycle_entries = [e for e in entries if e.type == "action_lifecycle"]
    assert len(lifecycle_entries) == 1
    assert lifecycle_entries[0].item_id == item.id
    assert lifecycle_entries[0].option_chosen == "done"


@pytest.mark.asyncio
async def test_change_priority(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/actions/{item.id}/priority",
        json={"priority": "P1"},
    )
    assert r.status_code == 200

    updated = await stores.items.get_item(item.id)
    assert updated.priority == Priority.P1


@pytest.mark.asyncio
async def test_snooze_action(client, app_with_state):
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        action_source="triage_response", action_category="delegation",
    )
    await stores.items.save_item(item)

    r = await client.post(
        f"/api/actions/{item.id}/snooze",
        json={"hours": 4},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "snoozed"


@pytest.mark.asyncio
async def test_action_not_found(client):
    r = await client.post("/api/actions/nonexistent/done")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_action_items_excluded(client, app_with_state):
    """Items without action_source should not appear in /api/actions."""
    stores = app_with_state.state.stores
    item = Item(
        source_type="email", source_id="e1",
        summary="Regular item", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED, priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        # No action_source set -- this is NOT an action item
    )
    await stores.items.save_item(item)

    r = await client.get("/api/actions")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_auth_token_endpoint(client, app_with_state):
    r = await client.get("/api/auth/token")
    assert r.status_code == 200
    data = r.json()
    assert data["token"] == "dev-token-change-me"
