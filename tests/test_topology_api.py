"""Topology API tests (Task B2, ADR 0041).

GET /api/topology composes the EXISTING health probes (storage, connections,
memory, messenger) into a {nodes, edges} component graph for the Overview
INFRASTRUCTURE 2D-SVG panel. It NEVER 5xxes for absent components (ADR 0016):
missing pieces render as not_configured / unknown, not errors.

These tests build a minimal FastAPI app that mounts ONLY the topology router and
sets app.state directly (mirrors tests/test_health_improved.py) so they exercise
composition logic without a live DB.
"""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.topology import router

NODE_KINDS = {"app", "storage", "memory_service", "connection", "adapter", "messenger"}
STATUSES = {"healthy", "degraded", "unhealthy", "unknown", "not_configured"}


def _adapter(adapter_type: str):
    a = MagicMock()
    a.adapter_type.return_value = adapter_type
    # No _inner: a bare adapter (not instrumented-wrapped).
    del a._inner
    return a


def _conn(healthy: bool = True):
    c = MagicMock()
    c.is_healthy.return_value = healthy
    return c


def _make_app(
    *,
    storage_healthy=True,
    connections=None,
    sources=None,
    config_sources=None,
    memory=None,
    messenger="unset",
):
    app = FastAPI()
    app.include_router(router)

    stores = MagicMock()
    if storage_healthy:
        stores.items.pool.fetchval = AsyncMock(return_value=1)
    else:
        stores.items.pool.fetchval = AsyncMock(side_effect=Exception("PG down"))
    app.state.stores = stores

    app.state.connections = connections or {}
    app.state.sources = sources or []

    # config.sources is the YAML truth (carries the `connection` key per source);
    # the topology maps connection->adapter from it (zipped with app.state.sources).
    config = MagicMock()
    config.sources = config_sources if config_sources is not None else []
    app.state.config = config

    if memory is None:
        memory = MagicMock()
        memory.memory_type = "http"
        memory.is_available = AsyncMock(return_value=True)
    app.state.memory = memory

    if messenger != "unset":
        app.state.messenger = messenger

    return app


def _nodes_by_id(data):
    return {n["id"]: n for n in data["nodes"]}


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #
def test_topology_shape_and_enums():
    app = _make_app()
    resp = TestClient(app).get("/api/topology")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"nodes", "edges"}
    for node in data["nodes"]:
        assert set(node.keys()) == {"id", "label", "kind", "status"}
        assert node["kind"] in NODE_KINDS
        assert node["status"] in STATUSES
    for edge in data["edges"]:
        assert set(edge.keys()) == {"from", "to", "kind"}


def test_core_nodes_always_present():
    app = _make_app()
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    assert nodes["app"]["kind"] == "app"
    assert nodes["app"]["status"] == "healthy"
    # storage node present and healthy
    storage = [n for n in nodes.values() if n["kind"] == "storage"]
    assert len(storage) == 1
    assert storage[0]["status"] == "healthy"
    # memory_service node present
    mem = [n for n in nodes.values() if n["kind"] == "memory_service"]
    assert len(mem) == 1


def test_core_edges_app_to_storage_and_memory():
    app = _make_app()
    data = TestClient(app).get("/api/topology").json()
    nodes = _nodes_by_id(data)
    storage_id = next(n["id"] for n in nodes.values() if n["kind"] == "storage")
    memory_id = next(n["id"] for n in nodes.values() if n["kind"] == "memory_service")
    pairs = {(e["from"], e["to"]) for e in data["edges"]}
    assert ("app", storage_id) in pairs
    assert ("app", memory_id) in pairs


# --------------------------------------------------------------------------- #
# Storage status
# --------------------------------------------------------------------------- #
def test_storage_unhealthy_does_not_5xx():
    app = _make_app(storage_healthy=False)
    resp = TestClient(app).get("/api/topology")
    assert resp.status_code == 200
    nodes = _nodes_by_id(resp.json())
    storage = next(n for n in nodes.values() if n["kind"] == "storage")
    assert storage["status"] == "unhealthy"


# --------------------------------------------------------------------------- #
# Connections + adapters
# --------------------------------------------------------------------------- #
def test_connection_and_adapter_nodes_and_edges():
    conn = _conn(healthy=True)
    adapter = _adapter("github")
    app = _make_app(
        connections={"github_api": conn},
        sources=[adapter],
        config_sources=[{"class": "x.GithubSource", "connection": "github_api"}],
    )
    data = TestClient(app).get("/api/topology").json()
    nodes = _nodes_by_id(data)

    conns = [n for n in nodes.values() if n["kind"] == "connection"]
    adapters = [n for n in nodes.values() if n["kind"] == "adapter"]
    assert len(conns) == 1
    assert conns[0]["status"] == "healthy"
    assert len(adapters) == 1
    assert adapters[0]["label"] == "github"

    pairs = {(e["from"], e["to"]) for e in data["edges"]}
    # app -> connection
    assert ("app", conns[0]["id"]) in pairs
    # connection -> adapter
    assert (conns[0]["id"], adapters[0]["id"]) in pairs


def test_unhealthy_connection_marks_adapter_degraded():
    conn = _conn(healthy=False)
    adapter = _adapter("github")
    app = _make_app(
        connections={"github_api": conn},
        sources=[adapter],
        config_sources=[{"class": "x.GithubSource", "connection": "github_api"}],
    )
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    conn_node = next(n for n in nodes.values() if n["kind"] == "connection")
    adapter_node = next(n for n in nodes.values() if n["kind"] == "adapter")
    assert conn_node["status"] == "unhealthy"
    # adapter inherits a degraded status from its unhealthy connection
    assert adapter_node["status"] == "degraded"


def test_connection_probe_exception_is_unknown_not_error():
    conn = MagicMock()
    conn.is_healthy.side_effect = Exception("boom")
    app = _make_app(connections={"flaky": conn})
    resp = TestClient(app).get("/api/topology")
    assert resp.status_code == 200
    nodes = _nodes_by_id(resp.json())
    conn_node = next(n for n in nodes.values() if n["kind"] == "connection")
    assert conn_node["status"] == "unknown"


# --------------------------------------------------------------------------- #
# Memory service
# --------------------------------------------------------------------------- #
def test_memory_noop_is_not_configured():
    from workbench.providers.memory.noop import NoopMemoryLayer

    app = _make_app(memory=NoopMemoryLayer())
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    mem = next(n for n in nodes.values() if n["kind"] == "memory_service")
    assert mem["status"] == "not_configured"


def test_memory_available_is_healthy():
    memory = MagicMock()
    memory.memory_type = "http"
    memory.is_available = AsyncMock(return_value=True)
    app = _make_app(memory=memory)
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    mem = next(n for n in nodes.values() if n["kind"] == "memory_service")
    assert mem["status"] == "healthy"


def test_memory_configured_but_down_is_unhealthy():
    memory = MagicMock()
    memory.memory_type = "http"
    memory.is_available = AsyncMock(return_value=False)
    app = _make_app(memory=memory)
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    mem = next(n for n in nodes.values() if n["kind"] == "memory_service")
    assert mem["status"] == "unhealthy"


def test_no_standalone_neo4j_or_meta_nodes():
    app = _make_app()
    data = TestClient(app).get("/api/topology").json()
    labels = " ".join(n["label"].lower() for n in data["nodes"])
    ids = " ".join(n["id"].lower() for n in data["nodes"])
    assert "neo4j" not in labels and "neo4j" not in ids
    assert "dcat" not in labels and "dcat" not in ids
    # only the generic kinds, never a meta-only kind
    for n in data["nodes"]:
        assert n["kind"] in NODE_KINDS


# --------------------------------------------------------------------------- #
# Messenger
# --------------------------------------------------------------------------- #
def test_messenger_node_unknown_without_reachability_probe():
    # A messenger object lacking is_reachable -> status unknown (no probe).
    messenger = MagicMock(spec=[])  # no is_reachable attribute
    app = _make_app(messenger=messenger)
    data = TestClient(app).get("/api/topology").json()
    nodes = _nodes_by_id(data)
    msg = next(n for n in nodes.values() if n["kind"] == "messenger")
    assert msg["status"] == "unknown"
    pairs = {(e["from"], e["to"]) for e in data["edges"]}
    assert ("app", msg["id"]) in pairs


def test_messenger_reachable_is_healthy():
    messenger = MagicMock()
    del messenger._inner  # bare messenger (not Instrumented-wrapped)
    messenger.is_reachable = AsyncMock(return_value=True)
    app = _make_app(messenger=messenger)
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    msg = next(n for n in nodes.values() if n["kind"] == "messenger")
    assert msg["status"] == "healthy"


def test_messenger_unreachable_is_unhealthy():
    messenger = MagicMock()
    del messenger._inner  # bare messenger (not Instrumented-wrapped)
    messenger.is_reachable = AsyncMock(return_value=False)
    app = _make_app(messenger=messenger)
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    msg = next(n for n in nodes.values() if n["kind"] == "messenger")
    assert msg["status"] == "unhealthy"


def test_no_messenger_is_not_configured():
    app = _make_app(messenger=None)
    nodes = _nodes_by_id(TestClient(app).get("/api/topology").json())
    msg = next(n for n in nodes.values() if n["kind"] == "messenger")
    assert msg["status"] == "not_configured"
