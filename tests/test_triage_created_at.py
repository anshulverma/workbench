"""Triage `created_at` tests (Task B4, ADR0047).

Covers the new `triage_cards.created_at` column added by migration 007:
  - round-trip: save_card then read (get_card / get_pending) preserves created_at
  - GET /api/triage/pending payload includes a serialized `created_at`

Backs the redesigned Triage page Time-Window filter (1H/24H/7D/ALL), which
keys off a real per-card row-birth timestamp. Runs against the live test DB.
"""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import TriageCard, TriageOption


# --------------------------------------------------------------------------- #
# Store round-trip
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_save_card_defaults_created_at(stores):
    """A freshly-modelled card gets a created_at and it survives the round trip."""
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="queued",
    )
    assert card.created_at is not None
    await stores.triage.save_card(card)

    fetched = await stores.triage.get_card(card.id)
    assert fetched is not None
    assert fetched.created_at is not None
    # Round-trip preserves the value (within DB microsecond precision)
    assert abs((fetched.created_at - card.created_at).total_seconds()) < 1


@pytest.mark.asyncio
async def test_save_card_preserves_explicit_created_at(stores):
    """An explicit created_at is persisted and read back unchanged."""
    ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="queued",
        created_at=ts,
    )
    await stores.triage.save_card(card)

    fetched = await stores.triage.get_card(card.id)
    assert fetched.created_at == ts


@pytest.mark.asyncio
async def test_get_pending_includes_created_at(stores):
    """get_pending() returns cards carrying created_at."""
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="queued",
    )
    await stores.triage.save_card(card)

    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].created_at is not None


# --------------------------------------------------------------------------- #
# API payload (mirrors tests/test_triage_web.py fixtures)
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 50)
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


@pytest.mark.asyncio
async def test_pending_payload_includes_created_at(client, app_with_state):
    """GET /api/triage/pending serializes created_at as an ISO-8601 string,
    while keeping the fields the web page already reads."""
    stores = app_with_state.state.stores
    ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    card = TriageCard(
        card_content={"summary": "hello", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="queued",
        created_at=ts,
    )
    await stores.triage.save_card(card)

    r = await client.get("/api/triage/pending")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    row = data[0]
    # New field, serialized as a JSON string
    assert "created_at" in row
    assert isinstance(row["created_at"], str)
    assert "2026-06-01" in row["created_at"]
    # Existing fields the web page already reads remain present
    for field in ("id", "card_content", "options", "relevance_score", "status"):
        assert field in row
