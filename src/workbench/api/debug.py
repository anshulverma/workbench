from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from workbench.redaction import redact_secrets as _redact_secrets

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/adapters")
async def debug_adapters(request: Request):
    sources = getattr(request.app.state, "sources", [])
    adapters = []
    for s in sources:
        inner = getattr(s, "_inner", s)
        adapters.append(
            {
                "name": getattr(s, "_name", type(inner).__name__),
                "class": type(inner).__qualname__,
                "healthy": getattr(
                    getattr(inner, "_connection", None), "is_healthy", lambda: True
                )(),
            }
        )
    return {"adapters": adapters}


@router.get("/connections")
async def debug_connections(request: Request):
    connections = getattr(request.app.state, "connections", {})
    result = {}
    for name, conn in connections.items():
        result[name] = {
            "class": type(conn).__qualname__,
            "healthy": conn.is_healthy(),
        }
    return {"connections": result}


@router.get("/pipeline")
async def debug_pipeline(request: Request):
    stores = request.app.state.stores
    try:
        rows = await stores.items.pool.fetch(
            "SELECT id, status, source_type, created_at FROM items ORDER BY created_at DESC LIMIT 50"
        )
        jobs = [dict(r) for r in rows]
    except Exception:
        logger.warning("debug_pipeline query failed")
        jobs = []
    return {"recent_items": jobs}


@router.get("/identity")
async def debug_identity(request: Request):
    memory = getattr(request.app.state, "memory", None)
    if not memory or not hasattr(memory, "get_identity_stats"):
        return {"message": "Identity resolution not available"}
    try:
        stats = await memory.get_identity_stats()
        return stats
    except Exception as e:
        logger.warning("debug_identity stats failed")
        return {"error": str(e)}


@router.get("/config")
async def debug_config(request: Request):
    config = request.app.state.config
    raw = config.model_dump() if hasattr(config, "model_dump") else {}
    return {"config": _redact_secrets(raw)}
