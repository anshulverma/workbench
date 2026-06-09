"""B6: per-source relevance/noise thresholds + hot-reload (ADR0044, ADR0013).

Covers:
  * PATCH /api/sources/{id} persists `relevance` to YAML + DB and reflects it.
  * Defaults (relevance=None) preserve the current global routing.
  * The pipeline routing honors per-source thresholds when present.
  * The targeted hot-reload applies the new thresholds without a restart
    (the live PipelineEngine's resolver returns the patched values).
"""

import asyncio

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.pipeline.engine import PipelineEngine
from workbench.providers.enrichment.stub import StubEnricher
from workbench.domain import (
    ExtractedItem,
    ItemCategory,
    ItemFilters,
    RawItem,
    SourceRelevanceConfig,
    TriageCard,
    TriageOption,
)


# --------------------------------------------------------------------------- #
# App + client fixtures (mirror test_sources_api.py hot-reload plumbing).
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = []
    llm.score_relevance.return_value = (50, 90)
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
    test_app.state.metrics = None
    test_app.state.pipeline = PipelineEngine(
        stores, NoopMemoryLayer(), mock_llm, StubEnricher()
    )
    test_app.state.reload_lock = asyncio.Lock()
    test_app.state.connections = {}
    test_app.state.config_path = None

    from workbench.pipeline.scheduler import WorkbenchScheduler

    sched = WorkbenchScheduler(
        stores,
        NoopMemoryLayer(),
        test_app.state.pipeline,
        None,
        test_config,
        sources=[],
        llm=mock_llm,
    )
    sched.scheduler.start()
    test_app.state.scheduler = sched

    yield test_app

    sched.scheduler.shutdown(wait=False)


@pytest_asyncio.fixture
async def client(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer dev-token-change-me"},
    ) as c:
        yield c


SAMPLE_CONFIG = """\
version: 0.4.0
server:
  api_token: dev-token-change-me
storage:
  postgres_dsn: ${oc.env:WB_TEST_DSN}
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
sources: []
"""


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "WB_TEST_DSN", "postgres://workbench:workbench@localhost:5432/workbench"
    )
    p = tmp_path / "config.yml"
    p.write_text(SAMPLE_CONFIG)
    monkeypatch.setenv("WORKBENCH_CONFIG", str(p))
    return str(p)


async def _create_github_source(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": ["a/b"]},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 200
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# 1. PATCH persists thresholds + reflected (YAML + DB + response).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_patch_relevance_persists_to_yaml_db_and_response(
    client, config_path, app_with_state
):
    source_id = await _create_github_source(client, config_path, app_with_state)

    r = await client.patch(
        f"/api/sources/{source_id}",
        json={
            "relevance": {
                "auto_include_threshold": 90,
                "triage_threshold": 40,
                "drop_below": 20,
            }
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["relevance"]["auto_include_threshold"] == 90
    assert body["relevance"]["drop_below"] == 20
    assert body["relevance"]["triage_threshold"] == 40

    # Written back to YAML (ADR0013 config write-back).
    out = open(config_path).read()
    assert "auto_include_threshold" in out
    assert "90" in out

    # Reflected in the DB store (round-trips on read).
    db = await app_with_state.state.stores.sources.get_source(source_id)
    assert db.relevance is not None
    assert db.relevance.auto_include_threshold == 90
    assert db.relevance.drop_below == 20

    # And reflected on the list endpoint.
    lst = await client.get("/api/sources")
    row = next(s for s in lst.json() if s["id"] == source_id)
    assert row["relevance"]["auto_include_threshold"] == 90


@pytest.mark.asyncio
async def test_patch_rejects_out_of_range_threshold(
    client, config_path, app_with_state
):
    source_id = await _create_github_source(client, config_path, app_with_state)
    r = await client.patch(
        f"/api/sources/{source_id}",
        json={"relevance": {"auto_include_threshold": 150}},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_rejects_inverted_thresholds(client, config_path, app_with_state):
    source_id = await _create_github_source(client, config_path, app_with_state)
    # drop_below above auto_include_threshold is nonsensical.
    r = await client.patch(
        f"/api/sources/{source_id}",
        json={
            "relevance": {
                "auto_include_threshold": 30,
                "drop_below": 80,
                "triage_threshold": 50,
            }
        },
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# 2. Defaults preserve current routing (relevance=None -> global thresholds).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_defaults_preserve_global_routing():
    engine = PipelineEngine(
        AsyncMock(),
        NoopMemoryLayer(),
        AsyncMock(),
        StubEnricher(),
        include_threshold=70,
        drop_threshold=30,
        confidence_threshold=70,
    )
    inc, drop, conf = engine.thresholds_for("github")
    assert (inc, drop, conf) == (70, 30, 70)


# --------------------------------------------------------------------------- #
# 3. Routing honors per-source thresholds.
# --------------------------------------------------------------------------- #
def _ext(source_type="github"):
    return ExtractedItem(
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        source_context="ctx",
        raw_item=RawItem(
            id="x1", source_type=source_type, source_label="l", raw_text="t"
        ),
    )


@pytest.mark.asyncio
async def test_routing_honors_per_source_thresholds(stores, mock_llm):
    # relevance=50: with the global include=70/drop=30 this is TRIAGE.
    mock_llm.score_relevance.return_value = (50, 90)
    engine = PipelineEngine(
        stores,
        NoopMemoryLayer(),
        mock_llm,
        StubEnricher(),
        include_threshold=70,
        drop_threshold=30,
        confidence_threshold=70,
    )

    # A per-source override lowering auto_include to 40 makes 50 AUTO-INCLUDE.
    engine.set_source_thresholds(
        "github",
        SourceRelevanceConfig(
            auto_include_threshold=40, triage_threshold=40, drop_below=20
        ),
    )
    inc, drop, conf = engine.thresholds_for("github")
    assert inc == 40 and drop == 20 and conf == 70

    job = None
    await engine._process_extracted_item(_ext("github"), job)
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].origin.value == "auto_included"
    assert items[0].status.value == "active"


@pytest.mark.asyncio
async def test_routing_per_source_drop(stores, mock_llm):
    # relevance=50 with a per-source drop_below=60 => DROP (no item stored).
    mock_llm.score_relevance.return_value = (50, 90)
    engine = PipelineEngine(
        stores,
        NoopMemoryLayer(),
        mock_llm,
        StubEnricher(),
        include_threshold=70,
        drop_threshold=30,
        confidence_threshold=70,
    )
    engine.set_source_thresholds(
        "github",
        SourceRelevanceConfig(
            auto_include_threshold=90, triage_threshold=60, drop_below=60
        ),
    )
    await engine._process_extracted_item(_ext("github"), None)
    assert len(await stores.items.get_items(ItemFilters())) == 0


@pytest.mark.asyncio
async def test_routing_other_source_uses_global(stores, mock_llm):
    # A per-source override on github must NOT affect a different source_type.
    mock_llm.score_relevance.return_value = (50, 90)
    engine = PipelineEngine(
        stores,
        NoopMemoryLayer(),
        mock_llm,
        StubEnricher(),
        include_threshold=70,
        drop_threshold=30,
        confidence_threshold=70,
    )
    engine.set_source_thresholds(
        "github",
        SourceRelevanceConfig(
            auto_include_threshold=40, triage_threshold=40, drop_below=20
        ),
    )
    # email has no override => global routing => relevance 50 is TRIAGE.
    await engine._process_extracted_item(_ext("email"), None)
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].status.value == "pending_triage"


# --------------------------------------------------------------------------- #
# 4. Hot-reload applies the patched thresholds to the LIVE engine, no restart.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_patch_hot_reloads_live_engine_thresholds(
    client, config_path, app_with_state
):
    source_id = await _create_github_source(client, config_path, app_with_state)
    engine = app_with_state.state.pipeline

    # Before: github resolves to the global thresholds.
    assert engine.thresholds_for("github") == (70, 30, 70)

    r = await client.patch(
        f"/api/sources/{source_id}",
        json={
            "relevance": {
                "auto_include_threshold": 45,
                "triage_threshold": 25,
                "drop_below": 15,
            }
        },
    )
    assert r.status_code == 200

    # After the targeted hot-reload, the SAME live engine returns the new values
    # with no restart / no re-instantiation of the app.
    assert engine.thresholds_for("github") == (45, 15, 70)
