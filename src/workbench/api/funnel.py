"""Funnel API — pipeline stage ordering, toggling, item funnel traces.

GET    /api/funnel/order                 — current pipeline stage order
PATCH  /api/funnel/order                 — reorder stages
PATCH  /api/funnel/stages/{stage_id}     — toggle a stage enabled/disabled
POST   /api/funnel/stages/{stage_id}/toggle — toggle a stage (UI alias)
GET    /api/funnel/items                 — items with funnel trace data (FunnelItem)
GET    /api/funnel/items/{item_id}       — single item funnel trace (FunnelItem)
GET    /api/items/{item_id}/funnel       — raw funnel trace for a single item

Funnel facade — the read/write contract the UI funnel (Filters) page consumes.
These mirror the lower-level resource routers (/api/filter-rules, /api/enrichers,
/api/loopbacks) but under the /api/funnel/* namespace and reshaped into the
view models the page renders:

GET    /api/funnel/filter-rules          — filter rules with match stats
POST   /api/funnel/filter-rules          — create a filter rule
DELETE /api/funnel/filter-rules/{id}     — delete a filter rule
GET    /api/funnel/enrichers             — enrichers + derived run stats
GET    /api/funnel/loopbacks             — loopbacks (view shape)
GET    /api/funnel/enrichment-samples    — recent enrichment samples per enricher
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from workbench.domain import EnrichmentTrace, FilterRule, TraceFilters

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


@router.post("/funnel/stages/{stage_id}/toggle")
async def toggle_stage_post(stage_id: str, body: StageToggle, request: Request):
    """UI alias for the stage toggle (the page POSTs .../toggle)."""
    store = _get_funnel_order_store(request)
    await store.toggle_stage(stage_id, body.enabled)
    return {"status": "ok", "stage_id": stage_id, "enabled": body.enabled}


# --------------------------------------------------------------------------- #
# Funnel item view shaping
# --------------------------------------------------------------------------- #
# verdict_action -> the funnel page's coarse decision bucket.
_DECISION = {
    "include": "triaged",
    "triage": "triaged",
    "triaged": "triaged",
    "drop": "dropped",
    "dropped": "dropped",
}


def _stage_view(entry: dict) -> dict:
    """Map one funnel_log entry to the UI FunnelStage shape (best-effort: the
    log entries are free-form dicts written by future pipeline stages)."""
    return {
        "filterId": entry.get("filterId")
        or entry.get("filter_id")
        or entry.get("stage")
        or "",
        "outcome": entry.get("outcome") or entry.get("action") or "pass",
        "reason": entry.get("reason"),
        "confidence": entry.get("confidence"),
        "label": entry.get("label"),
        "context": entry.get("context"),
        "weak": entry.get("weak"),
    }


def _funnel_item_view(item) -> dict:
    action = (item.verdict_action or "").lower()
    return {
        "id": item.id,
        "summary": item.summary,
        "source": item.source_type,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "stages": [_stage_view(e) for e in (item.funnel_log or [])],
        "verdict": {
            "decision": _DECISION.get(action, "queued"),
            "priority": item.verdict_priority,
            "confidence": item.verdict_confidence,
            "rationale": next(
                (
                    e.get("reason")
                    for e in reversed(item.funnel_log or [])
                    if e.get("reason")
                ),
                "",
            ),
        },
    }


@router.get("/funnel/items")
async def get_funnel_items(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
):
    """Recent items that carry funnel trace data, in the UI FunnelItem shape."""
    stores = request.app.state.stores
    items = await stores.items.items_recent(limit)
    views = [_funnel_item_view(i) for i in items if i.funnel_log]
    if source:
        views = [v for v in views if v["source"] == source]
    if verdict:
        views = [v for v in views if v["verdict"]["decision"] == verdict]
    return views


@router.get("/funnel/items/{item_id}")
async def get_funnel_item(item_id: str, request: Request):
    """Single item in the UI FunnelItem shape."""
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return _funnel_item_view(item)


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


# --------------------------------------------------------------------------- #
# Funnel facade — filter rules
# --------------------------------------------------------------------------- #
@router.get("/funnel/filter-rules")
async def funnel_filter_rules(request: Request):
    """All filter rules, ordered by their funnel position."""
    stores = request.app.state.stores
    rules = await stores.filter_rules.get_rules()
    return sorted(rules, key=lambda r: r.order_index)


class FilterRuleCreate(BaseModel):
    prompt: str
    action: str
    sources: list[str] = []


@router.post("/funnel/filter-rules")
async def funnel_create_filter_rule(body: FilterRuleCreate, request: Request):
    stores = request.app.state.stores
    rule = FilterRule(
        prompt=body.prompt,
        action=body.action,
        sources=body.sources,
        origin="explicit",
    )
    return await stores.filter_rules.add_rule(rule)


@router.delete("/funnel/filter-rules/{rule_id}")
async def funnel_delete_filter_rule(rule_id: str, request: Request):
    stores = request.app.state.stores
    await stores.filter_rules.delete_rule(rule_id)
    return {"status": "deleted"}


# --------------------------------------------------------------------------- #
# Funnel facade — enrichers + loopbacks (config -> UI view shapes)
# --------------------------------------------------------------------------- #
def _enricher_view(enricher, traces: list[EnrichmentTrace]) -> dict:
    cfg = enricher.config or {}
    matching = [t for t in traces if t.depth == enricher.stage]
    enriched = len(matching)
    avg_ms = round(sum(t.time_ms for t in matching) / enriched) if enriched else 0
    budget = cfg.get("budget") or {}
    return {
        "id": enricher.id,
        "type": enricher.provider,
        "label": enricher.name,
        "depth": cfg.get("depth", "shallow"),
        "enabled": enricher.enabled,
        "adds": cfg.get("adds", []),
        "records": cfg.get("records", []),
        "budget": {
            "max_calls": budget.get("max_calls", 1),
            "max_time_ms": budget.get("max_time_ms", 5000),
        },
        "avg_ms": avg_ms,
        "enriched": enriched,
    }


def _loopback_view(loopback) -> dict:
    cfg = loopback.config or {}
    return {
        "id": loopback.id,
        "label": loopback.name,
        "trigger": loopback.trigger,
        "condition": cfg.get("condition", loopback.trigger),
        "max_loops": loopback.max_iterations,
        "enabled": loopback.enabled,
        "looped": cfg.get("looped", 0),
        "avg_loops": cfg.get("avg_loops", 0),
    }


@router.get("/funnel/enrichers")
async def funnel_enrichers(request: Request):
    stores = request.app.state.stores
    if stores.enrichers is None:
        return []
    enrichers = await stores.enrichers.get_enrichers()
    traces = await stores.enrichment.get_traces(TraceFilters())
    return [_enricher_view(e, traces) for e in enrichers]


@router.get("/funnel/loopbacks")
async def funnel_loopbacks(request: Request):
    stores = request.app.state.stores
    if stores.loopbacks is None:
        return []
    loopbacks = await stores.loopbacks.get_loopbacks()
    return [_loopback_view(lb) for lb in loopbacks]


@router.get("/funnel/enrichment-samples")
async def funnel_enrichment_samples(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
):
    """Recent enrichment samples grouped by enricher id.

    For each enricher, surfaces the most recent traces of its stage as
    {id, summary, context, entities} sample records (UI EnrichmentSample).
    """
    stores = request.app.state.stores
    if stores.enrichers is None:
        return {}
    enrichers = await stores.enrichers.get_enrichers()
    traces = await stores.enrichment.get_traces(TraceFilters())

    summaries: dict[str, str] = {}

    async def _summary(item_id: str) -> str:
        if item_id not in summaries:
            item = await stores.items.get_item(item_id)
            summaries[item_id] = item.summary if item else item_id
        return summaries[item_id]

    out: dict[str, list[dict]] = {}
    for enricher in enrichers:
        matching = [t for t in traces if t.depth == enricher.stage][:limit]
        samples = []
        for trace in matching:
            context = trace.context_retrieved or {}
            sample = {
                "id": trace.item_id,
                "summary": await _summary(trace.item_id),
                "context": context,
            }
            entities = context.get("entities")
            if entities:
                sample["entities"] = entities
            samples.append(sample)
        out[enricher.id] = samples
    return out
