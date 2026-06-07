import asyncio

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.pipeline.engine import PipelineEngine
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import TriageCard, TriageOption


# --------------------------------------------------------------------------- #
# Fixtures (file-local, mirror test_api.py / test_stats_api.py) but with the
# hot-reload plumbing (reload_lock, config_path, connections) and a real
# scheduler so Targeted Hot-Reload swap + job registration is exercised.
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

    # Inject the API token so auth is enforced deterministically (see test_stats_api).
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


@pytest.mark.asyncio
async def test_adapter_types_lists_allowlist(client):
    r = await client.get("/api/sources/adapter-types")
    assert r.status_code == 200
    types = {t["adapter_type"] for t in r.json()}
    assert types == {"github", "email", "calendar", "chat"}
    gh = next(t for t in r.json() if t["adapter_type"] == "github")
    assert gh["requires_connection"] is False
    assert "properties" in gh["json_schema"]
    email = next(t for t in r.json() if t["adapter_type"] == "email")
    assert email["requires_connection"] is True


@pytest.mark.asyncio
async def test_create_source_writes_yaml_and_db(client, app_with_state, config_path):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": ["meta/workbench"]},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 200
    source_id = r.json()["id"]
    out = open(config_path).read()
    assert source_id in out
    assert "meta/workbench" in out
    db = await app_with_state.state.stores.sources.get_source(source_id)
    assert db is not None and db.adapter_type == "github"


@pytest.mark.asyncio
async def test_create_added_to_state_and_scheduler(client, app_with_state, config_path):
    app_with_state.state.config_path = config_path
    before = len(app_with_state.state.sources)
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": ["x/y"]},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 200
    source_id = r.json()["id"]
    assert len(app_with_state.state.sources) == before + 1
    sched = app_with_state.state.scheduler
    assert source_id in sched._source_by_id
    assert sched.scheduler.get_job(f"poll_source:{source_id}") is not None


@pytest.mark.asyncio
async def test_create_rejects_unknown_adapter_type(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "diff",
            "config": {},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 422
    # nothing written to YAML
    assert "diff" not in open(config_path).read()


@pytest.mark.asyncio
async def test_create_rejects_bad_cron(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": []},
            "schedule": "not a cron",
            "enabled": True,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_invalid_config_field(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": "should-be-a-list"},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 422
    # bad config => NO YAML write
    assert "should-be-a-list" not in open(config_path).read()


@pytest.mark.asyncio
async def test_patch_rejects_adapter_type_change(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": []},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    source_id = r.json()["id"]
    r = await client.patch(f"/api/sources/{source_id}", json={"adapter_type": "email"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_updates_and_reschedules(client, config_path, app_with_state):
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
    source_id = r.json()["id"]
    r = await client.patch(
        f"/api/sources/{source_id}",
        json={"config": {"repos": ["c/d"]}, "schedule": "*/30 * * * *"},
    )
    assert r.status_code == 200
    db = await app_with_state.state.stores.sources.get_source(source_id)
    assert db.config == {"repos": ["c/d"]}
    assert db.schedule == "*/30 * * * *"
    assert "c/d" in open(config_path).read()


@pytest.mark.asyncio
async def test_patch_disable_removes_job(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": []},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    source_id = r.json()["id"]
    sched = app_with_state.state.scheduler
    assert sched.scheduler.get_job(f"poll_source:{source_id}") is not None
    r = await client.patch(f"/api/sources/{source_id}", json={"enabled": False})
    assert r.status_code == 200
    assert sched.scheduler.get_job(f"poll_source:{source_id}") is None


@pytest.mark.asyncio
async def test_delete_removes_yaml_and_db(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": []},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    source_id = r.json()["id"]
    sched = app_with_state.state.scheduler
    r = await client.delete(f"/api/sources/{source_id}")
    assert r.status_code == 200
    out = open(config_path).read()
    assert source_id not in out
    assert await app_with_state.state.stores.sources.get_source(source_id) is None
    assert source_id not in sched._source_by_id
    assert sched.scheduler.get_job(f"poll_source:{source_id}") is None


@pytest.mark.asyncio
async def test_poll_now_triggers_run(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "github",
            "config": {"repos": []},
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    source_id = r.json()["id"]
    r = await client.post(f"/api/sources/{source_id}/poll")
    assert r.status_code == 200
    latest = await app_with_state.state.stores.ingestion_runs.latest_for_source(
        source_id
    )
    assert latest is not None
    assert latest.status in ("success", "error")


@pytest.mark.asyncio
async def test_poll_now_404_unknown(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources/nope/poll")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_email_source_without_connection_rejected(
    client, config_path, app_with_state
):
    app_with_state.state.config_path = config_path
    app_with_state.state.connections = {}
    r = await client.post(
        "/api/sources",
        json={
            "adapter_type": "email",
            "config": {},
            "connection": "google",
            "schedule": "*/15 * * * *",
            "enabled": True,
        },
    )
    assert r.status_code == 422
    # nothing written
    assert "email" not in open(config_path).read()


@pytest.mark.asyncio
async def test_connections_endpoint_no_secrets(client, app_with_state):
    class _Conn:
        service_account_key_path = "/secret/sa.json"

        def is_healthy(self):
            return True

    app_with_state.state.connections = {"google": _Conn()}
    r = await client.get("/api/connections")
    assert r.status_code == 200
    data = r.json()
    assert data == [{"name": "google", "healthy": True}]
    assert "/secret/sa.json" not in str(data)


@pytest.mark.asyncio
async def test_sources_require_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/sources", json={})
        assert r.status_code == 401
