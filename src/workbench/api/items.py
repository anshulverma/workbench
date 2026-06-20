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


_RELATED_CAP = 50

_HREF = {
    "llm_call": lambda e: f"/llm/{e['id']}" if e["id"] is not None else None,
    "interaction": lambda e: f"/interactions/{e['id']}",
    "message": lambda e: f"/messages/{e['id']}",
    "triage_card": lambda e: None,
    "enrichment_trace": lambda e: None,
    "feedback_correction": lambda e: None,
    "plan": lambda e: None,
}


@router.get("/items/{path}/related")
async def item_related(path: str, request: Request, subtree: bool = Query(False)):
    """Entities that touched ``path`` (and descendants when subtree=true),
    grouped by entity_type: UNION of entity_item_links (joined to llm_calls for
    correlation-only id resolution) and the three depth-0 FK tables."""
    stores = request.app.state.stores
    pool = stores.items.pool

    if subtree:
        path_pred = "(eil.item_path = $1 OR eil.item_path LIKE $1 || '.%')"
        fk_pred = "(i.path = $1 OR i.path LIKE $1 || '.%')"
    else:
        path_pred = "eil.item_path = $1"
        fk_pred = "i.path = $1"

    # entity_item_links side. For llm_call rows whose entity_id is NULL
    # (correlation-only), resolve via llm_calls.correlation_id.
    link_rows = await pool.fetch(
        f"""
        SELECT eil.entity_type,
               COALESCE(eil.entity_id, lc.id) AS id,
               eil.item_path,
               eil.created_at,
               lc.purpose AS lc_purpose,
               lc.status  AS lc_status
          FROM entity_item_links eil
          LEFT JOIN llm_calls lc
            ON eil.entity_type = 'llm_call'
           AND eil.entity_id IS NULL
           AND lc.correlation_id = eil.correlation_id
         WHERE {path_pred}
         ORDER BY eil.created_at DESC, eil.id DESC
        """,
        path,
    )

    groups: dict[str, list] = {}

    def _push(entity_type: str, entry: dict) -> None:
        bucket = groups.setdefault(entity_type, [])
        if len(bucket) < _RELATED_CAP:
            href_fn = _HREF.get(entity_type, lambda e: None)
            entry["href"] = href_fn(entry)
            bucket.append(entry)

    for r in link_rows:
        et = r["entity_type"]
        eid = r["id"]
        if et == "llm_call":
            label = f"{r['lc_purpose'] or 'llm_call'} · {r['lc_status'] or '?'}"
        else:
            label = f"{et} #{eid}" if eid is not None else et
        _push(
            et,
            {
                "entity_type": et,
                "id": eid,
                "label": label,
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    # Three FK tables, filtered by item path.
    tc_rows = await pool.fetch(
        f"SELECT tc.id, tc.created_at FROM triage_cards tc "
        f"JOIN items i ON i.id = tc.item_id WHERE {fk_pred} "
        f"ORDER BY tc.created_at DESC",
        path,
    )
    for r in tc_rows:
        _push(
            "triage_card",
            {
                "entity_type": "triage_card",
                "id": r["id"],
                "label": f"card #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    et_rows = await pool.fetch(
        f"SELECT et.id, et.timestamp AS created_at FROM enrichment_trace et "
        f"JOIN items i ON i.id = et.item_id WHERE {fk_pred} "
        f"ORDER BY et.timestamp DESC",
        path,
    )
    for r in et_rows:
        _push(
            "enrichment_trace",
            {
                "entity_type": "enrichment_trace",
                "id": r["id"],
                "label": f"enrichment #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    fc_rows = await pool.fetch(
        f"SELECT fc.id, fc.created_at FROM feedback_corrections fc "
        f"JOIN items i ON i.id = fc.item_id WHERE {fk_pred} "
        f"ORDER BY fc.created_at DESC",
        path,
    )
    for r in fc_rows:
        _push(
            "feedback_correction",
            {
                "entity_type": "feedback_correction",
                "id": r["id"],
                "label": f"feedback #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    counts = {et: len(entries) for et, entries in groups.items()}
    return {"path": path, "subtree": subtree, "counts": counts, "groups": groups}


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
