"""Connections API: names + health only. NEVER secrets.

Connections are defined in YAML and require a restart to change. This endpoint
exposes only the connection name and a boolean health flag derived from
``is_healthy()`` (when available) -- never service_account_key_path, tokens,
or DSNs.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["connections"])


@router.get("/connections")
async def list_connections(request: Request):
    connections = getattr(request.app.state, "connections", {})
    result = []
    for name, conn in connections.items():
        healthy = True
        if hasattr(conn, "is_healthy"):
            try:
                healthy = bool(conn.is_healthy())
            except Exception:
                healthy = False
        result.append({"name": name, "healthy": healthy})
    return result
