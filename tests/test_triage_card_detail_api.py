import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from unittest.mock import AsyncMock, patch

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import TriageCard, TriageOption


@pytest.fixture
def _mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 50)
    return llm


@pytest_asyncio.fixture
async def triage_app(stores, _mock_llm):
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
    test_app.state.llm = _mock_llm
    test_app.state.enricher = StubEnricher()
    test_app.state.messenger = None
    test_app.state.queue_scorer = None
    test_app.state.sources = []
    test_app.state.pipeline = PipelineEngine(
        stores, NoopMemoryLayer(), _mock_llm, StubEnricher()
    )
    yield test_app, stores


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer dev-token-change-me"}


async def _client(app):
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_card_by_id_returns_full_card(triage_app, auth_headers):
    app, stores = triage_app
    card = TriageCard(
        card_content={
            "content_schema": "diff.v1",
            "sections": {"summary": "adds retry", "metadata": {"author": "alice"}},
            "card_body": "adds retry",
            "summary": "adds retry",
        },
        options=[TriageOption(label="Add P1", action="add_todo")],
        relevance_score=80,
    )
    await stores.triage.save_card(card)

    client = await _client(app)
    resp = await client.get(f"/api/triage/cards/{card.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == card.id
    assert body["card_content"]["content_schema"] == "diff.v1"
    assert body["card_content"]["sections"]["summary"] == "adds retry"
    assert body["relevance_score"] == 80
    await client.aclose()


@pytest.mark.asyncio
async def test_get_unknown_card_returns_404(triage_app, auth_headers):
    app, _ = triage_app
    client = await _client(app)
    resp = await client.get("/api/triage/cards/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_get_card_without_bearer_is_unauthorized(triage_app):
    app, stores = triage_app
    card = TriageCard(card_content={"summary": "x"}, options=[])
    await stores.triage.save_card(card)
    client = await _client(app)
    resp = await client.get(f"/api/triage/cards/{card.id}")
    assert resp.status_code in (401, 403)
    await client.aclose()
