from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from workbench.domain import ItemFilters, ItemUpdate

router = APIRouter(prefix="/api", tags=["items"])

_SEARCH_MAX_LIMIT = 100
_SEARCH_DEFAULT_LIMIT = 50


@router.get("/items")
async def list_items(
    request: Request,
    priority: str = None,
    status: str = None,
    source_type: str = None,
):
    stores = request.app.state.stores
    filters = ItemFilters(priority=priority, status=status, source_type=source_type)
    return await stores.items.get_items(filters)


@router.get("/items/search")
async def search_items(
    request: Request,
    q: str = Query(""),
    kind: str | None = Query(None),
    limit: int = Query(_SEARCH_DEFAULT_LIMIT),
):
    """Rich full-text search over items.

    Returns SearchItem results with llm_summary, enriched_context,
    processing_log (funnel_log), verdict, and tags.
    Limit is capped at 100 regardless of what the client requests.
    """
    limit = min(max(1, limit), _SEARCH_MAX_LIMIT)
    q = (q or "").strip()

    if len(q) < 2:
        return {"q": q, "results": [], "total": 0}

    stores = request.app.state.stores
    pool = stores.items.pool

    # Escape ILIKE wildcards
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    query = """
        SELECT id, source_type, source_id, summary, category, origin,
               priority, status, created_at, updated_at,
               tags, llm_summary, enriched_context, funnel_log,
               verdict_action, verdict_priority, verdict_confidence,
               action_source, path
          FROM items
         WHERE summary ILIKE '%' || $1 || '%' ESCAPE '\\'
    """
    params: list = [escaped]
    idx = 2

    if kind:
        if kind == "action":
            query += " AND action_source IS NOT NULL"
        elif kind == "item":
            query += " AND action_source IS NULL"
        elif kind != "all":
            query += f" AND category = ${idx}"
            params.append(kind)
            idx += 1

    query += " ORDER BY created_at DESC LIMIT $" + str(idx)
    params.append(limit)

    rows = await pool.fetch(query, *params)

    import json

    results = []
    for r in rows:
        tags = r.get("tags")
        if isinstance(tags, str):
            tags = json.loads(tags)

        enriched_context = r.get("enriched_context")
        if isinstance(enriched_context, str):
            enriched_context = json.loads(enriched_context)

        funnel_log = r.get("funnel_log")
        if isinstance(funnel_log, str):
            funnel_log = json.loads(funnel_log)

        results.append(
            {
                "id": r["id"],
                "source_type": r["source_type"],
                "source_id": r["source_id"],
                "summary": r["summary"],
                "category": r["category"],
                "origin": r["origin"],
                "priority": r["priority"],
                "status": r["status"],
                "kind": "action" if r.get("action_source") else "item",
                "path": r.get("path"),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "tags": tags or [],
                "llm_summary": r.get("llm_summary"),
                "enriched_context": enriched_context or {},
                "processing_log": funnel_log or [],
                "verdict": {
                    "action": r.get("verdict_action"),
                    "priority": r.get("verdict_priority"),
                    "confidence": r.get("verdict_confidence"),
                },
            }
        )

    return {"q": q, "results": results, "total": len(results)}


@router.get("/items/{path}")
async def get_item_by_path(path: str, request: Request):
    stores = request.app.state.stores
    item = await stores.items.get_by_path(path)
    if not item:
        raise HTTPException(404, "Item not found")
    ancestors = await stores.items.get_ancestors(item)
    children = await stores.items.get_children(item.id)
    return {
        "item": item.model_dump(mode="json"),
        "ancestors": [
            {"id": a.id, "path": a.path, "summary": a.summary, "status": a.status}
            for a in ancestors
        ],
        "children": [
            {
                "id": c.id,
                "path": c.path,
                "seq": c.seq,
                "summary": c.summary,
                "status": c.status,
                "priority": c.priority,
                "has_children": has,
            }
            for c, has in children
        ],
    }


@router.patch("/items/{item_id}")
async def update_item(item_id: int, updates: ItemUpdate, request: Request):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return await stores.items.update_item(item_id, updates)


@router.delete("/items/{item_id}")
async def archive_item(item_id: int, request: Request):
    stores = request.app.state.stores
    await stores.items.archive_item(item_id)
    return {"status": "archived"}


class SnoozeBody(BaseModel):
    hours: int = 4


@router.post("/items/{item_id}/snooze")
async def snooze_item(item_id: int, body: SnoozeBody, request: Request):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    until = datetime.now(timezone.utc) + timedelta(hours=body.hours)
    pool = stores.items.pool
    await pool.execute(
        "UPDATE items SET snoozed_until = $1, updated_at = NOW() WHERE id = $2",
        until,
        item_id,
    )
    return {"status": "snoozed", "until": until.isoformat()}
