"""Feedback API tests (Slice 3).

Covers GET/POST/DELETE corrections, GET/POST/PATCH/DELETE tasks,
and lifecycle of feedback corrections and tuning tasks.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import (
    FeedbackCorrection,
    FilterTuningTask,
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
# Corrections CRUD
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_corrections_empty(client):
    r = await client.get("/api/feedback/corrections")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_add_and_list_correction(client, stores):
    # Seed an item first
    item = Item(
        source_type="github",
        source_id="fb-1",
        summary="Test item",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)

    correction = FeedbackCorrection(
        item_id=item.id,
        original_action="drop",
        corrected_action="include",
        reason="Should not have been dropped",
    )

    r = await client.post(
        "/api/feedback/corrections",
        json=correction.model_dump(mode="json"),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["item_id"] == item.id
    assert data["corrected_action"] == "include"

    # List all
    r = await client.get("/api/feedback/corrections")
    assert r.status_code == 200
    corrections = r.json()
    assert len(corrections) >= 1

    # Filter by item_id
    r = await client.get(f"/api/feedback/corrections?item_id={item.id}")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_delete_correction(client, stores):
    item = Item(
        source_type="github",
        source_id="fb-del-1",
        summary="Delete test",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.AUTO_INCLUDED,
        priority=Priority.P2,
    )
    await stores.items.save_item(item)

    correction = FeedbackCorrection(
        item_id=item.id,
        original_action="drop",
        corrected_action="include",
    )
    r = await client.post(
        "/api/feedback/corrections",
        json=correction.model_dump(mode="json"),
    )
    cid = r.json()["id"]

    r = await client.delete(f"/api/feedback/corrections/{cid}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"


# --------------------------------------------------------------------------- #
# Tasks lifecycle
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_task_lifecycle(client, stores):
    from workbench.domain import FilterRule

    rule = FilterRule(action="drop", pattern="test")
    await stores.filter_rules.add_rule(rule)

    task = FilterTuningTask(
        rule_id=rule.id,
        proposed_prompt="Refined: exclude only test flakes",
        correction_ids=[],
    )

    # Create
    r = await client.post(
        "/api/feedback/tasks",
        json=task.model_dump(mode="json"),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "open"
    task_id = data["id"]

    # List all
    r = await client.get("/api/feedback/tasks")
    assert r.status_code == 200
    assert len(r.json()) >= 1

    # List by status
    r = await client.get("/api/feedback/tasks?status=open")
    assert r.status_code == 200
    assert all(t["status"] == "open" for t in r.json())

    # Update status
    r = await client.patch(f"/api/feedback/tasks/{task_id}?status=applied")
    assert r.status_code == 200
    assert r.json()["status"] == "applied"

    # Delete
    r = await client.delete(f"/api/feedback/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
