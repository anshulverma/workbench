from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory/entities", tags=["identity"])


def _get_memory_client(request: Request):
    """Get the HTTP client and base_url from the memory layer, if available."""
    memory = request.app.state.memory
    if not hasattr(memory, "_client") or not hasattr(memory, "_base_url"):
        return None, None
    return memory._client, memory._base_url


@router.get("")
async def list_entities(
    request: Request,
    entity_type: str = Query(None),
    canonical_id: str = Query(None),
):
    """List entities with canonical mappings. Proxies to memory service."""
    client, base_url = _get_memory_client(request)
    if client is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Memory service not configured for HTTP access"},
        )
    try:
        params = {}
        if entity_type and canonical_id:
            params = {"entity_type": entity_type, "canonical_id": canonical_id}
            resp = await client.get(
                f"{base_url}/admin/identity/list", params=params,
            )
        else:
            # No specific filter -- return empty for now (memory service
            # doesn't have a blanket list-all endpoint yet)
            return {"entities": [], "total": 0}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Memory service list entities failed: %s", e)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Memory service error: {e}"},
        )


@router.post("/{entity_type}/{entity_id}/merge")
async def merge_entity(
    request: Request,
    entity_type: str,
    entity_id: str,
    loser_id: str = Query(..., description="The entity ID to merge into this one"),
):
    """Manually merge loser entity into this entity. Proxies to memory service."""
    client, base_url = _get_memory_client(request)
    if client is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Memory service not configured for HTTP access"},
        )
    try:
        resp = await client.post(
            f"{base_url}/admin/identity/merge",
            params={
                "entity_type": entity_type,
                "winner_id": entity_id,
                "loser_id": loser_id,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Memory service merge failed: %s", e)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Memory service error: {e}"},
        )


@router.delete("/{entity_type}/{entity_id}/identity")
async def split_identity(
    request: Request,
    entity_type: str,
    entity_id: str,
):
    """Split this entity out of its canonical group. Proxies to memory service."""
    client, base_url = _get_memory_client(request)
    if client is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Memory service not configured for HTTP access"},
        )
    try:
        resp = await client.post(
            f"{base_url}/admin/identity/split",
            params={
                "entity_type": entity_type,
                "source_id": entity_id,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Memory service split failed: %s", e)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Memory service error: {e}"},
        )
