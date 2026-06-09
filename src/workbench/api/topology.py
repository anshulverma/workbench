"""Infrastructure topology API (Task B2, ADR 0041).

GET /api/topology composes the EXISTING component health probes — storage
(PostgreSQL), shared connections, the memory service, configured source
adapters, and the messenger — into a small, fixed node-link graph for the
Overview INFRASTRUCTURE panel. The client renders it as a hand-rolled 2D SVG
(no react-three-fiber / reactflow) with a visually-hidden a11y table fallback.

Contract (ADR 0016): this endpoint NEVER 5xxes for an absent or unreachable
component. Missing pieces are reported as ``not_configured``; probe failures as
``unknown``; degraded dependencies cascade to ``degraded`` — they are never
surfaced as HTTP errors.

Response::

    {
      "nodes": [{"id", "label", "kind", "status"}, ...],
      "edges": [{"from", "to", "kind"}, ...]
    }

    kind   ∈ {app, storage, memory_service, connection, adapter, messenger}
    status ∈ {healthy, degraded, unhealthy, unknown, not_configured}

Composition rules (OSS-generic only — NO meta-only / dcat nodes; neo4j is
folded into the single memory_service node, no standalone probe):

* ``app``            — the FastAPI app; always healthy if it can answer.
* ``storage``        — PostgreSQL; ``SELECT 1`` -> healthy, else unhealthy.
* ``memory_service`` — NoopMemoryLayer -> not_configured; configured+available
                       -> healthy; configured+down -> unhealthy.
* one ``connection`` per configured shared connection; is_healthy() ->
                       healthy/unhealthy, probe raise -> unknown.
* one ``adapter`` per configured source; inherits its connection's status
                       (degraded if the connection is not healthy), unknown when
                       it has no resolvable connection.
* ``messenger``      — no messenger -> not_configured; is_reachable() ->
                       healthy/unhealthy; no reachability probe -> unknown.

Edges: app->storage, app->memory_service, app->each connection,
connection->adapter, app->messenger.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["topology"])

APP_NODE_ID = "app"
STORAGE_NODE_ID = "storage"
MEMORY_NODE_ID = "memory"
MESSENGER_NODE_ID = "messenger"


def _node(node_id: str, label: str, kind: str, status: str) -> dict:
    return {"id": node_id, "label": label, "kind": kind, "status": status}


def _edge(src: str, dst: str, kind: str) -> dict:
    return {"from": src, "to": dst, "kind": kind}


async def _storage_status(stores) -> str:
    if stores is None:
        return "not_configured"
    try:
        await stores.items.pool.fetchval("SELECT 1")
        return "healthy"
    except Exception as e:
        logger.warning("topology_storage_probe_failed", error=str(e))
        return "unhealthy"


async def _memory_status(memory) -> str:
    if memory is None:
        return "not_configured"
    memory_type = getattr(memory, "memory_type", "unknown")
    # NoopMemoryLayer (or any noop type) means the memory service is absent.
    if memory_type == "noop":
        return "not_configured"
    try:
        available = await memory.is_available()
    except Exception as e:
        logger.warning("topology_memory_probe_failed", error=str(e))
        return "unknown"
    return "healthy" if available else "unhealthy"


def _connection_status(conn) -> str:
    if not hasattr(conn, "is_healthy"):
        return "unknown"
    try:
        return "healthy" if conn.is_healthy() else "unhealthy"
    except Exception as e:
        logger.warning("topology_connection_probe_failed", error=str(e))
        return "unknown"


async def _messenger_status(messenger) -> str:
    if messenger is None:
        return "not_configured"
    inner = getattr(messenger, "_inner", messenger)
    if not hasattr(inner, "is_reachable"):
        # No cheap reachability probe (e.g. GoogleChat): status is unknown.
        return "unknown"
    try:
        return "healthy" if await inner.is_reachable() else "unhealthy"
    except Exception as e:
        logger.warning("topology_messenger_probe_failed", error=str(e))
        return "unknown"


def _adapter_type(adapter) -> str:
    inner = getattr(adapter, "_inner", adapter)
    try:
        return inner.adapter_type()
    except Exception:
        return type(inner).__name__


@router.get("/topology")
async def get_topology(request: Request):
    state = request.app.state
    stores = getattr(state, "stores", None)
    connections = getattr(state, "connections", {}) or {}
    sources = getattr(state, "sources", []) or []
    config = getattr(state, "config", None)
    config_sources = list(getattr(config, "sources", []) or []) if config else []
    memory = getattr(state, "memory", None)
    messenger = getattr(state, "messenger", None)

    nodes: list[dict] = [_node(APP_NODE_ID, "Workbench", "app", "healthy")]
    edges: list[dict] = []

    # Storage (PostgreSQL).
    nodes.append(
        _node(STORAGE_NODE_ID, "PostgreSQL", "storage", await _storage_status(stores))
    )
    edges.append(_edge(APP_NODE_ID, STORAGE_NODE_ID, "connection"))

    # Memory service (neo4j folded in here; no standalone node).
    nodes.append(
        _node(
            MEMORY_NODE_ID,
            "Memory Service",
            "memory_service",
            await _memory_status(memory),
        )
    )
    edges.append(_edge(APP_NODE_ID, MEMORY_NODE_ID, "connection"))

    # Shared connections (one node each) + app->connection edges.
    connection_node_ids: dict[str, str] = {}
    for name, conn in connections.items():
        node_id = f"conn:{name}"
        connection_node_ids[name] = node_id
        status = _connection_status(conn)
        nodes.append(_node(node_id, name, "connection", status))
        edges.append(_edge(APP_NODE_ID, node_id, "connection"))

    # Map each connection node to its derived status for adapter cascade.
    connection_status_by_name = {
        name: next(n["status"] for n in nodes if n["id"] == nid)
        for name, nid in connection_node_ids.items()
    }

    # Source adapters (one node each). The YAML config sections (zipped with the
    # live adapters, as in main.py) carry the `connection` reference used to draw
    # the connection->adapter edge and cascade status. An adapter whose
    # connection is missing/unhealthy is degraded; with no connection at all it
    # is unknown.
    for idx, adapter in enumerate(sources):
        node_id = f"adapter:{idx}"
        label = _adapter_type(adapter)
        section = config_sources[idx] if idx < len(config_sources) else {}
        conn_name = section.get("connection") if isinstance(section, dict) else None

        if conn_name and conn_name in connection_node_ids:
            conn_status = connection_status_by_name.get(conn_name, "unknown")
            if conn_status == "healthy":
                adapter_status = "healthy"
            elif conn_status == "unknown":
                adapter_status = "unknown"
            else:
                # connection unhealthy/degraded -> adapter degraded.
                adapter_status = "degraded"
            nodes.append(_node(node_id, label, "adapter", adapter_status))
            edges.append(_edge(connection_node_ids[conn_name], node_id, "adapter"))
        else:
            # No resolvable connection: we cannot probe the adapter's health.
            nodes.append(_node(node_id, label, "adapter", "unknown"))

    # Messenger.
    nodes.append(
        _node(
            MESSENGER_NODE_ID,
            "Messenger",
            "messenger",
            await _messenger_status(messenger),
        )
    )
    edges.append(_edge(APP_NODE_ID, MESSENGER_NODE_ID, "messenger"))

    return {"nodes": nodes, "edges": edges}
