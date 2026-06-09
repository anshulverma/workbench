"""Messenger info/edit API tests (Task C1).

Covers GET/PATCH /api/messenger against the live PostgreSQL test DB.

GET always returns 200 with a {configured, type, class, config} envelope
(ADR 0016). The config is allowlist-on-output: only non-secret fields are
ever serialized; service_account_key_path / secrets MUST NOT appear.

PATCH writes the messenger node back to YAML via config_writer.write_messenger
(ADR 0013) and hot-swaps app.state.messenger plus the scheduler's messenger
and alert_manager messenger references, all under app.state.reload_lock.

Fixtures (mock_llm, app_with_state, client) mirror tests/test_stats_api.py.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.pipeline.engine import PipelineEngine
from workbench.domain import TriageCard, TriageOption


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
async def app_with_state(stores, mock_llm, tmp_path):
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

    # Hot-reload plumbing for PATCH.
    import asyncio

    test_app.state.reload_lock = asyncio.Lock()

    # A real config.yml written to a temp dir so write_messenger can round-trip.
    # The messenger node carries a ${oc.env:...} secret interpolation that must
    # survive write-back (never resolved to plaintext on disk).
    config_yml = tmp_path / "config.yml"
    config_yml.write_text(
        "version: 0.4.0\n"
        "messenger:\n"
        "  class: workbench.providers.messenger.google_chat.GoogleChatMessenger\n"
        "  space_id: spaces/OLD\n"
        "  service_account_key_path: ${oc.env:SA_PATH}\n"
        "  timeout_seconds: 30\n"
    )
    test_app.state.config_path = str(config_yml)
    # The live (resolved) config view: OmegaConf would have resolved the env ref
    # to a real path. The handler carries this forward so instantiation can
    # validate without the browser ever supplying the secret.
    test_config.messenger = {
        "class": "workbench.providers.messenger.google_chat.GoogleChatMessenger",
        "space_id": "spaces/OLD",
        "service_account_key_path": "/resolved/sa.json",
        "timeout_seconds": 30,
    }

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
# Test doubles
# --------------------------------------------------------------------------- #
class _FakeMessenger:
    """Stand-in shaped like GoogleChatMessenger with a _config object."""

    class _Cfg:
        space_id = "spaces/AAA"
        timeout_seconds = 5
        service_account_key_path = "/secret/sa.json"

    def __init__(self):
        self._config = self._Cfg()

    async def is_reachable(self):
        return True


class _FlatGChatLike:
    """Stand-in shaped like the real GoogleChatMessenger (flat attributes)."""

    def __init__(self):
        self.space_id = "spaces/BBB"
        self._key_path = "/secret/flat.json"
        self._timeout = 30


class _Scheduler:
    """Minimal scheduler double with messenger + alert_manager refs."""

    def __init__(self, messenger):
        self.messenger = messenger

        class _AM:
            pass

        self.alert_manager = _AM()
        self.alert_manager.messenger = messenger

    def set_messenger(self, new):
        self.messenger = new
        self.alert_manager.messenger = new


# --------------------------------------------------------------------------- #
# GET — envelope + auth
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_messenger_get_degraded_when_none(client, app_with_state):
    app_with_state.state.messenger = None
    r = await client.get("/api/messenger")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is False
    assert data["type"] == "none"
    assert data["class"] is None
    assert data["config"] == {}


@pytest.mark.asyncio
async def test_messenger_get_allowlisted_config_no_secret(client, app_with_state):
    app_with_state.state.messenger = _FakeMessenger()
    r = await client.get("/api/messenger")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is True
    assert data["class"].endswith("_FakeMessenger")
    assert data["config"]["space_id"] == "spaces/AAA"
    assert data["config"]["timeout_seconds"] == 5
    assert "service_account_key_path" not in data["config"]
    assert "/secret/sa.json" not in str(data)


@pytest.mark.asyncio
async def test_messenger_get_flat_gchat_like_no_secret(client, app_with_state):
    """Real GoogleChatMessenger stores space_id/_timeout as flat attributes."""
    app_with_state.state.messenger = _FlatGChatLike()
    r = await client.get("/api/messenger")
    data = r.json()
    assert data["config"]["space_id"] == "spaces/BBB"
    # _key_path is a secret and must never surface.
    assert "/secret/flat.json" not in str(data)
    assert "_key_path" not in data["config"]
    assert "service_account_key_path" not in data["config"]


@pytest.mark.asyncio
async def test_messenger_get_short_type_console(client, app_with_state):
    from workbench.providers.messenger.console import ConsoleMessenger

    app_with_state.state.messenger = ConsoleMessenger()
    r = await client.get("/api/messenger")
    data = r.json()
    assert data["type"] == "console"
    assert data["config"] == {}


@pytest.mark.asyncio
async def test_messenger_get_short_type_google_chat(client, app_with_state):
    from workbench.providers.messenger.google_chat import GoogleChatMessenger

    cfg = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/CCC",
        service_account_key_path="/secret/real.json",
        timeout_seconds=10,
    )
    app_with_state.state.messenger = GoogleChatMessenger(cfg)
    r = await client.get("/api/messenger")
    data = r.json()
    assert data["type"] == "google_chat"
    assert data["config"]["space_id"] == "spaces/CCC"
    assert data["config"]["timeout_seconds"] == 10
    assert "/secret/real.json" not in str(data)
    assert "service_account_key_path" not in data["config"]


@pytest.mark.asyncio
async def test_messenger_get_check_adds_reachability_fake(client, app_with_state):
    app_with_state.state.messenger = _FakeMessenger()
    r = await client.get("/api/messenger?check=true")
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is True
    assert "checked_at" in data


@pytest.mark.asyncio
async def test_messenger_get_check_console_always_reachable(client, app_with_state):
    from workbench.providers.messenger.console import ConsoleMessenger

    app_with_state.state.messenger = ConsoleMessenger()
    r = await client.get("/api/messenger?check=true")
    data = r.json()
    assert data["reachable"] is True
    assert "checked_at" in data


@pytest.mark.asyncio
async def test_messenger_get_check_gchat_no_probe_reachable_null(
    client, app_with_state
):
    """GoogleChat has no cheap probe: reachable is null, with a note, no crash."""
    from workbench.providers.messenger.google_chat import GoogleChatMessenger

    cfg = GoogleChatMessenger.ProviderConfig(
        space_id="spaces/DDD",
        service_account_key_path="/secret/real.json",
        timeout_seconds=10,
    )
    app_with_state.state.messenger = GoogleChatMessenger(cfg)
    r = await client.get("/api/messenger?check=true")
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is None
    assert "checked_at" in data
    assert "note" in data


@pytest.mark.asyncio
async def test_messenger_get_no_check_does_not_probe(client, app_with_state):
    app_with_state.state.messenger = _FakeMessenger()
    r = await client.get("/api/messenger")
    data = r.json()
    assert "reachable" not in data
    assert "checked_at" not in data


@pytest.mark.asyncio
async def test_messenger_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/messenger")
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# PATCH — write-back + hot-swap
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_messenger_patch_writes_yaml_and_hot_swaps(client, app_with_state):
    from workbench.providers.messenger.console import ConsoleMessenger

    old = ConsoleMessenger()
    app_with_state.state.messenger = old
    sched = _Scheduler(old)
    app_with_state.state.scheduler = sched

    body = {
        "class": "workbench.providers.messenger.google_chat.GoogleChatMessenger",
        "space_id": "spaces/NEW",
        "timeout_seconds": 12,
    }
    r = await client.patch("/api/messenger", json=body)
    assert r.status_code == 200

    # app.state.messenger swapped.
    new = app_with_state.state.messenger
    assert new is not old
    assert type(new).__name__ == "GoogleChatMessenger"
    assert new.space_id == "spaces/NEW"

    # scheduler + alert_manager both rebound.
    assert sched.messenger is new
    assert sched.alert_manager.messenger is new

    # YAML written: safe fields present, secret interpolation preserved.
    text = open(app_with_state.state.config_path).read()
    assert "spaces/NEW" in text
    assert "timeout_seconds: 12" in text
    # The pre-existing service_account_key_path env interpolation must be intact
    # and no resolved secret value written.
    assert "${oc.env:SA_PATH}" in text
    assert "/resolved/sa.json" not in text


@pytest.mark.asyncio
async def test_messenger_patch_short_type_maps_to_class(client, app_with_state):
    from workbench.providers.messenger.console import ConsoleMessenger

    old = ConsoleMessenger()
    app_with_state.state.messenger = old
    app_with_state.state.scheduler = _Scheduler(old)

    body = {"type": "console"}
    r = await client.patch("/api/messenger", json=body)
    assert r.status_code == 200
    assert type(app_with_state.state.messenger).__name__ == "ConsoleMessenger"


@pytest.mark.asyncio
async def test_messenger_patch_bad_config_422_no_write(client, app_with_state):
    from workbench.providers.messenger.console import ConsoleMessenger

    old = ConsoleMessenger()
    app_with_state.state.messenger = old
    app_with_state.state.scheduler = _Scheduler(old)
    # Existing config is console: switching to google_chat has nothing to carry
    # forward, so the required secret is genuinely missing.
    app_with_state.state.config.messenger = {
        "class": "workbench.providers.messenger.console.ConsoleMessenger"
    }

    before = open(app_with_state.state.config_path).read()

    # google_chat requires space_id + service_account_key_path; omit them.
    body = {"type": "google_chat", "timeout_seconds": 5}
    r = await client.patch("/api/messenger", json=body)
    assert r.status_code == 422

    # No swap, no write.
    assert app_with_state.state.messenger is old
    after = open(app_with_state.state.config_path).read()
    assert after == before


@pytest.mark.asyncio
async def test_messenger_patch_rejects_secret_in_body(client, app_with_state):
    """Secrets (service_account_key_path) must not be accepted from the body."""
    from workbench.providers.messenger.console import ConsoleMessenger

    old = ConsoleMessenger()
    app_with_state.state.messenger = old
    app_with_state.state.scheduler = _Scheduler(old)
    before = open(app_with_state.state.config_path).read()

    body = {
        "type": "google_chat",
        "space_id": "spaces/X",
        "service_account_key_path": "/secret/injected.json",
    }
    r = await client.patch("/api/messenger", json=body)
    assert r.status_code == 422
    after = open(app_with_state.state.config_path).read()
    assert after == before
    assert "/secret/injected.json" not in after
