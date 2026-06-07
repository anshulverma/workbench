"""Stats & aggregation API (Design Section 3).

Returns pre-computed aggregates only (COUNT ... GROUP BY); never entity rows.
All routes are bearer-authed by the global middleware. Output is allowlisted —
no secrets / config-derived values are returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
async def overview(request: Request):
    """Top-level dashboard counts + items breakdown.

    Qualifies Ingested Counts distinctly: in_flight (queued+processing) vs
    dead_letters; never conflates them.
    """
    stores = request.app.state.stores
    by_status = await stores.items.count_by_status()
    by_priority = await stores.items.count_by_priority()
    by_category = await stores.items.count_by_category()
    by_source = await stores.items.count_by_source()
    pending = await stores.triage.get_pending()
    in_flight = await stores.ingestion_queue.queue_depth()
    dead = await stores.ingestion_queue.count_dead_letters()
    db_sources = await stores.sources.get_sources()
    enabled = sum(1 for s in db_sources if s.enabled)
    total_items = sum(by_status.values())
    return {
        "pending_triage": len(pending),
        "in_flight": in_flight,
        "dead_letters": dead,
        "active_items": by_status.get("active", 0),
        "sources_enabled": enabled,
        "sources_total": len(db_sources),
        "items": {
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_source": by_source,
            "total": total_items,
        },
        "queue": {
            "in_flight": in_flight,
            "dead_letters": dead,
        },
    }


@router.get("/queue")
async def queue(request: Request):
    """Ingestion queue health: by_status + by_source + dead_letter count."""
    stores = request.app.state.stores
    by_status = await stores.ingestion_queue.count_by_status()
    by_source = await stores.ingestion_queue.count_by_source()
    return {
        "by_status": by_status,
        "by_source": by_source,
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "dead_letter": by_status.get("dead_letter", 0),
    }


@router.get("/sources")
async def sources(request: Request):
    """Per-source rollup: qualified Ingested Counts + Source Health Status.

    Computed from DB source configs + COUNT-by-source aggregates + latest run.
    """
    stores = request.app.state.stores
    db_sources = await stores.sources.get_sources()
    items_by_source = await stores.items.count_by_source()
    raw_by_source = await stores.ingestion_queue.count_by_source()
    result = []
    for s in db_sources:
        latest = await stores.ingestion_runs.latest_for_source(s.id)
        if not s.enabled:
            health = "disabled"
        elif latest is None:
            health = "never_run"
        elif latest.status == "error":
            health = "erroring"
        else:
            health = "healthy"
        result.append(
            {
                "id": s.id,
                "adapter_type": s.adapter_type,
                "enabled": s.enabled,
                "schedule": s.schedule,
                "last_run": (
                    latest.finished_at.isoformat()
                    if latest and latest.finished_at
                    else None
                ),
                "items_stored": items_by_source.get(s.adapter_type, 0),
                "raw_enqueued": raw_by_source.get(s.adapter_type, 0),
                "in_flight": raw_by_source.get(s.adapter_type, 0),
                "health_status": health,
            }
        )
    return result


@router.get("/ingestion-timeseries")
async def ingestion_timeseries(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    bucket: str = Query("day"),
):
    """Items ingested per bucket via date_trunc over ingestion_runs."""
    stores = request.app.state.stores
    series = await stores.ingestion_runs.timeseries(days=days, bucket=bucket)
    return [{"date": ts.isoformat(), "count": n} for ts, n in series]
