"""LLM usage tracking API tests.

Covers GET /api/llm/calls (list view), GET /api/llm/calls/{call_id} (detail view),
and GET /api/llm/metrics (24h metrics).
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import (
    LlmCallRecord,
    LlmSubcall,
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
    test_app.sources = []
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
# GET /api/llm/calls — List view
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_calls_list_returns_summary_view(client, app_with_state):
    """List view returns summary fields only, no prompt/completion/subcalls."""
    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)

    rec = LlmCallRecord(
        started_at=now,
        origin="pipeline",
        purpose="extract entities",
        stage="extract",
        model="claude-4",
        temperature=0.7,
        status="ok",
        batch=2,
        items=["item1", "item2"],
        tokens_in=100,
        tokens_out=50,
        latency_ms=1500,
        system_prompt="Extract things",
        subcalls=[
            LlmSubcall(
                item="item1",
                prompt="Extract from this",
                completion="Found: X",
                tokens_in=50,
                tokens_out=25,
            )
        ],
    )
    await stores.llm_calls.save_many([rec])

    r = await client.get("/api/llm/calls?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1

    row = data[0]
    # Must have the exact UI field names
    assert row["id"].startswith("llm_")
    assert "ts" in row
    assert row["origin"] == "pipeline"
    assert row["purpose"] == "extract entities"
    assert row["stage"] == "extract"
    assert row["model"] == "claude-4"
    assert row["temperature"] == 0.7  # non-null number
    assert row["status"] == "ok"
    assert row["batch"] == 2
    assert row["items"] == ["item1", "item2"]
    assert row["tokens_in"] == 100
    assert row["tokens_out"] == 50
    assert row["latency_ms"] == 1500

    # No prompt/completion/subcalls in list view
    assert "prompt" not in row
    assert "completion" not in row
    assert "subcalls" not in row
    assert "sysPrompt" not in row


@pytest.mark.asyncio
async def test_llm_calls_list_temperature_defaults_to_zero(client, app_with_state):
    """When temperature is None, UI contract demands a number 0.0."""
    stores = app_with_state.state.stores

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="test",
        purpose="test",
        stage="extract",
        model="claude-4",
        temperature=None,
        status="ok",
        tokens_in=10,
    )
    await stores.llm_calls.save_many([rec])

    r = await client.get("/api/llm/calls")
    assert r.status_code == 200
    data = r.json()
    assert data[0]["temperature"] == 0.0  # not None


@pytest.mark.asyncio
async def test_llm_calls_list_filters_by_stage(client, app_with_state):
    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)

    await stores.llm_calls.save_many(
        [
            LlmCallRecord(
                started_at=now,
                origin="p",
                purpose="p",
                stage="extract",
                model="m",
                status="ok",
                tokens_in=1,
            ),
            LlmCallRecord(
                started_at=now,
                origin="p",
                purpose="p",
                stage="triage",
                model="m",
                status="ok",
                tokens_in=1,
            ),
        ]
    )

    r = await client.get("/api/llm/calls?stage=extract")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["stage"] == "extract"


@pytest.mark.asyncio
async def test_llm_calls_list_pagination_with_before_cursor(client, app_with_state):
    """before cursor format is '<iso_ts>,<id>' - verify it parses and doesn't crash."""
    stores = app_with_state.state.stores

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="cursor_test",
        purpose="test",
        stage="extract",
        model="m",
        status="ok",
        tokens_in=1,
    )
    await stores.llm_calls.save_many([rec])

    # Get one record
    r = await client.get("/api/llm/calls?limit=1")
    assert r.status_code == 200
    first = r.json()[0]

    # Build cursor and verify the API accepts it without crashing
    cursor = f"{first['ts']},{first['id'].replace('llm_', '')}"
    r2 = await client.get(f"/api/llm/calls?limit=10&before={cursor}")
    assert r2.status_code == 200
    # The cursor was parsed and passed to the store (doesn't crash = success)
    assert isinstance(r2.json(), list)


@pytest.mark.asyncio
async def test_llm_calls_list_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/llm/calls")
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# GET /api/llm/calls/{call_id} — Detail view
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_call_detail_returns_prompt_and_subcalls(client, app_with_state):
    stores = app_with_state.state.stores

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="pipeline",
        purpose="extract",
        stage="extract",
        model="claude-4",
        status="ok",
        tokens_in=100,
        system_prompt="You are an extractor",
        subcalls=[
            LlmSubcall(
                item="item1",
                prompt="Extract from this",
                completion="Found: X",
                tokens_in=50,
                tokens_out=25,
            ),
            LlmSubcall(
                item="item2",
                prompt="Extract from that",
                completion="Found: Y",
                tokens_in=50,
                tokens_out=25,
            ),
        ],
    )
    await stores.llm_calls.save_many([rec])

    # Fetch the saved record to get its ID
    saved = (await stores.llm_calls.list_calls(limit=1))[0]

    r = await client.get(f"/api/llm/calls/llm_{saved.id}")
    assert r.status_code == 200
    data = r.json()

    assert data["sysPrompt"] == "You are an extractor"
    assert "subcalls" in data
    assert len(data["subcalls"]) == 2
    assert data["subcalls"][0]["item"] == "item1"
    assert data["subcalls"][0]["prompt"] == "Extract from this"
    assert data["subcalls"][0]["completion"] == "Found: X"


@pytest.mark.asyncio
async def test_llm_call_detail_empty_system_prompt(client, app_with_state):
    stores = app_with_state.state.stores

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="test",
        purpose="test",
        stage="extract",
        model="m",
        status="ok",
        tokens_in=1,
        system_prompt=None,
        subcalls=[],
    )
    await stores.llm_calls.save_many([rec])

    # Fetch the saved record to get its ID
    saved = (await stores.llm_calls.list_calls(limit=1))[0]

    r = await client.get(f"/api/llm/calls/llm_{saved.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["sysPrompt"] == ""  # not None


@pytest.mark.asyncio
async def test_llm_call_detail_not_found(client):
    r = await client.get("/api/llm/calls/llm_999999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_llm_call_detail_bad_id_format(client):
    # Missing "llm_" prefix
    r = await client.get("/api/llm/calls/123")
    assert r.status_code == 404

    # Non-numeric
    r = await client.get("/api/llm/calls/llm_notanumber")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_detail_view_exposes_raw_io(client, app_with_state):
    stores = app_with_state.state.stores
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
        subcalls=[
            LlmSubcall(
                item="i1",
                prompt="p",
                completion="c",
                structured={"a": 1},
                tokens_in=1,
                tokens_out=1,
            )
        ],
        raw_request={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        raw_response={"stop_reason": "end_turn"},
    )
    await stores.llm_calls.save_many([rec])
    row = (await stores.llm_calls.list_calls(limit=1))[0]

    r = await client.get(f"/api/llm/calls/llm_{row.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["rawRequest"]["messages"][0]["content"] == "hi"
    assert body["rawResponse"]["stop_reason"] == "end_turn"


# --------------------------------------------------------------------------- #
# GET /api/llm/metrics — 24h metrics
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_metrics_returns_24h_summary(client, app_with_state):
    stores = app_with_state.state.stores
    now = datetime.now(timezone.utc)

    # Seed some calls
    await stores.llm_calls.save_many(
        [
            LlmCallRecord(
                started_at=now,
                origin="p",
                purpose="p",
                stage="extract",
                model="m",
                status="ok",
                tokens_in=100,
                latency_ms=500,
            ),
            LlmCallRecord(
                started_at=now,
                origin="p",
                purpose="p",
                stage="triage",
                model="m",
                status="error",
                error_type="timeout",
                tokens_in=50,
                latency_ms=1000,
            ),
        ]
    )

    r = await client.get("/api/llm/metrics")
    assert r.status_code == 200
    data = r.json()

    # Must have the standard metrics from metrics_24h()
    assert "calls_24h" in data
    assert "avg_latency_ms" in data
    assert "error_rate" in data
    assert "batched_pct" in data

    # Plus metadata
    assert data["window_hours"] == 24
    assert "as_of" in data

    # Check values
    assert data["calls_24h"] == 2
    assert data["error_rate"] == 0.5  # 1 error / 2 total


@pytest.mark.asyncio
async def test_llm_metrics_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/llm/metrics")
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# 503 guard — unconfigured store
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_calls_503_when_store_unconfigured(app_with_state):
    """When llm_calls store is None, return 503."""
    # Temporarily unconfigure the store
    original_store = app_with_state.state.stores.llm_calls
    app_with_state.state.stores.llm_calls = None

    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        r = await c.get("/api/llm/calls")
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]

        r2 = await c.get("/api/llm/calls/llm_1")
        assert r2.status_code == 503

        r3 = await c.get("/api/llm/metrics")
        assert r3.status_code == 503

    # Restore
    app_with_state.state.stores.llm_calls = original_store
