"""Funnel API — pipeline stage ordering, toggling, item funnel traces.

GET   /api/funnel/order                 — current pipeline stage order
PATCH /api/funnel/order                 — reorder stages
PATCH /api/funnel/stages/{stage_id}     — toggle a stage enabled/disabled
GET   /api/funnel/items                 — items with funnel trace data
GET   /api/items/{item_id}/funnel       — full funnel trace for a single item
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["funnel"])


def _get_funnel_order_store(request: Request):
    stores = request.app.state.stores
    if stores.funnel_order is None:
        raise HTTPException(503, "Funnel order store not configured")
    return stores.funnel_order


def _get_funnel_traces_store(request: Request):
    stores = request.app.state.stores
    if stores.funnel_traces is None:
        raise HTTPException(503, "Funnel traces store not configured")
    return stores.funnel_traces


@router.get("/funnel/order")
async def get_funnel_order(request: Request):
    store = _get_funnel_order_store(request)
    return await store.get_order()


class FunnelOrderUpdate(BaseModel):
    entries: list[dict]


@router.patch("/funnel/order")
async def update_funnel_order(body: FunnelOrderUpdate, request: Request):
    store = _get_funnel_order_store(request)
    await store.set_order(body.entries)
    return await store.get_order()


class StageToggle(BaseModel):
    enabled: bool


@router.patch("/funnel/stages/{stage_id}")
async def toggle_stage(stage_id: str, body: StageToggle, request: Request):
    store = _get_funnel_order_store(request)
    await store.toggle_stage(stage_id, body.enabled)
    return {"stage_id": stage_id, "enabled": body.enabled}


@router.get("/funnel/items")
async def get_funnel_items(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """Return recent items that have funnel trace data."""
    stores = request.app.state.stores
    items = await stores.items.items_recent(limit)
    # Filter to items with non-empty funnel_log
    return [i for i in items if i.funnel_log]


@router.get("/items/{item_id}/funnel")
async def get_item_funnel(item_id: str, request: Request):
    """Full funnel trace for a single item.

    Returns funnel_log from the item itself plus any stages recorded
    in the funnel_traces store.
    """
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    traces_store = _get_funnel_traces_store(request)
    stages = await traces_store.get_stages(item_id)

    return {
        "item_id": item_id,
        "funnel_log": item.funnel_log,
        "stages": stages,
        "verdict": {
            "action": item.verdict_action,
            "priority": item.verdict_priority,
            "confidence": item.verdict_confidence,
        },
    }
