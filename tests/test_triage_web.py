"""Triage web-respond API tests (Task C3).

Covers the 409 optimistic-concurrency guard on POST /api/triage/respond,
the web-native POST /api/triage/confirm flow for destructive free-text
responses, and the interaction-log audit gap closure -- all against the
live PostgreSQL test DB.

Fixtures (mock_llm, app_with_state, client) mirror tests/test_api.py and
additionally wire app.state.scheduler (needed for the free-text/confirm path).
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import (
    TriageCard,
    TriageOption,
    InterpretedResponse,
    SystemAction,
)


# --------------------------------------------------------------------------- #
# Fixtures (file-local, mirrors test_api.py, with scheduler wired)
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

    from workbench.pipeline.scheduler import WorkbenchScheduler

    test_scheduler = WorkbenchScheduler(
        stores,
        NoopMemoryLayer(),
        test_app.state.pipeline,
        None,
        test_config,
        sources=[],
        llm=mock_llm,
    )
    test_app.state.scheduler = test_scheduler

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
# 409 optimistic-concurrency guard
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_respond_409_on_already_responded(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="responded",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "choice": 1})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_respond_409_on_expired(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="expired",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "choice": 1})
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# Free-text destructive flow -> awaiting_confirmation + audit entry
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_destructive_free_text_returns_awaiting_confirmation(
    client, app_with_state
):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="sent",
    )
    await stores.triage.save_card(card)
    llm = AsyncMock()
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="skip")],
        explanation="will skip",
    )
    app_with_state.state.llm = llm
    r = await client.post(
        "/api/triage/respond", json={"card_id": card.id, "raw_text": "drop it"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "awaiting_confirmation"
    assert data["explanation"] == "will skip"
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "awaiting_confirmation"
    # audit gap closed: an InteractionEntry exists for the destructive-pending branch
    entries = await stores.interactions.get_all()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_confirm_executes_destructive(client, app_with_state):
    stores = app_with_state.state.stores
    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")], explanation="skip"
    )
    card = TriageCard(
        card_content={
            "summary": "x",
            "source_type": "github",
            "pending_interpreted": interpreted.model_dump(),
        },
        options=[TriageOption(label="Skip", action="skip")],
        status="awaiting_confirmation",
    )
    await stores.triage.save_card(card)
    r = await client.post(
        "/api/triage/confirm", json={"card_id": card.id, "confirm": True}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "responded"
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "responded"
    # confirm executing the action creates an InteractionEntry
    entries = await stores.interactions.get_all()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_confirm_cancel_returns_card_to_sent(client, app_with_state):
    stores = app_with_state.state.stores
    interpreted = InterpretedResponse(
        system_actions=[SystemAction(action="skip")], explanation="skip"
    )
    card = TriageCard(
        card_content={
            "summary": "x",
            "source_type": "github",
            "pending_interpreted": interpreted.model_dump(),
        },
        options=[TriageOption(label="Skip", action="skip")],
        status="awaiting_confirmation",
    )
    await stores.triage.save_card(card)
    r = await client.post(
        "/api/triage/confirm", json={"card_id": card.id, "confirm": False}
    )
    assert r.status_code == 200
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "sent"


# --------------------------------------------------------------------------- #
# Numbered (choice) response still works and logs an InteractionEntry (regression)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_numbered_response_creates_interaction_entry(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="sent",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "choice": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    entries = await stores.interactions.get_all()
    assert len(entries) == 1
    assert entries[0].choice_index == 1
