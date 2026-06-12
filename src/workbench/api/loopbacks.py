"""LoopBacks API — list configured loopback (re-processing) stages.

GET /api/loopbacks               — list all loopback configs
GET /api/loopbacks/{loopback_id} — get single loopback
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["loopbacks"])


def _get_loopbacks_store(request: Request):
    stores = request.app.state.stores
    if stores.loopbacks is None:
        raise HTTPException(503, "LoopBacks store not configured")
    return stores.loopbacks


@router.get("/loopbacks")
async def list_loopbacks(request: Request):
    store = _get_loopbacks_store(request)
    return await store.get_loopbacks()


@router.get("/loopbacks/{loopback_id}")
async def get_loopback(loopback_id: str, request: Request):
    store = _get_loopbacks_store(request)
    loopback = await store.get_loopback(loopback_id)
    if not loopback:
        raise HTTPException(404, "Loopback not found")
    return loopback
