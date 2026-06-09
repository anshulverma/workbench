"""Stats & aggregation API (Design Section 3).

Returns pre-computed aggregates only (COUNT ... GROUP BY); never entity rows.
All routes are bearer-authed by the global middleware. Output is allowlisted —
no secrets / config-derived values are returned.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])

# Derived-metrics windows (ADR0039/0040, spec §6). No caching.
_SIGNAL_VELOCITY_HOURS = 24
_THROUGHPUT_HOURS = 8
_AUTO_RESOLVED_HOURS = 24
_INGESTION_SUCCESS_DAYS = 7

# /api/stats/timeseries allow-lists (422 on anything else).
_TIMESERIES_METRICS = {"signal_velocity", "throughput"}
_TIMESERIES_BUCKETS = {"hour", "day"}


def _zero_filled(
    rows: list[tuple[datetime, int]], window: int, bucket: str
) -> list[dict]:
    """Build the full bucket axis (window buckets back from now), left-joining
    grouped counts and filling missing buckets with 0 (ADR0039 — never omit).
    """
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    now = datetime.now(timezone.utc)
    if bucket == "hour":
        anchor = now.replace(minute=0, second=0, microsecond=0)
    else:
        anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)

    counts: dict[datetime, int] = {}
    for ts, n in rows:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        counts[ts] = counts.get(ts, 0) + n

    series: list[dict] = []
    for i in range(window - 1, -1, -1):
        b = anchor - step * i
        series.append({"bucket": b.isoformat(), "count": counts.get(b, 0)})
    return series


async def _build_metrics(request: Request) -> dict:
    """Honest derived scalars. Any zero denominator / degraded source → None
    (rendered "n/a"); never fabricated (ADR0040)."""
    stores = request.app.state.stores
    memory = request.app.state.memory

    signal_velocity = await stores.items.count_created_since(_SIGNAL_VELOCITY_HOURS)

    # throughput = action items completed (completed_at) in the window.
    completed_rows = await stores.items.completed_timeseries(_THROUGHPUT_HOURS, "hour")
    throughput = sum(n for _, n in completed_rows)

    # efficiency_peak = max bucket close-rate (completed/created) over 24h/hour;
    # None when no bucket has any created items.
    created_rows = await stores.items.created_timeseries(_SIGNAL_VELOCITY_HOURS, "hour")
    created_24h = await stores.items.completed_timeseries(
        _SIGNAL_VELOCITY_HOURS, "hour"
    )
    created_by_bucket: dict[datetime, int] = {}
    for ts, n in created_rows:
        created_by_bucket[ts] = created_by_bucket.get(ts, 0) + n
    completed_by_bucket: dict[datetime, int] = {}
    for ts, n in created_24h:
        completed_by_bucket[ts] = completed_by_bucket.get(ts, 0) + n
    efficiency_peak = None
    for ts, created in created_by_bucket.items():
        if created <= 0:
            continue
        rate = min(completed_by_bucket.get(ts, 0) / created, 1.0)
        if efficiency_peak is None or rate > efficiency_peak:
            efficiency_peak = rate

    # auto_resolved_pct = auto_included / all over the window; None when empty.
    auto, total = await stores.items.auto_resolved_counts(_AUTO_RESOLVED_HOURS)
    auto_resolved_pct = (auto / total) if total > 0 else None

    avg_triage_seconds = await stores.triage.avg_triage_seconds()
    if avg_triage_seconds is not None:
        avg_triage_seconds = round(avg_triage_seconds)

    ingestion_success_rate = await stores.ingestion_runs.success_rate(
        _INGESTION_SUCCESS_DAYS
    )

    # growth_velocity = facts-added delta; degraded (None) under NoopMemory.
    growth_velocity = None
    if getattr(memory, "memory_type", "noop") != "noop":
        # No persisted facts-history series exists; insufficient history → None.
        growth_velocity = None

    return {
        "signal_velocity": signal_velocity,
        "throughput": throughput,
        "efficiency_peak": efficiency_peak,
        "auto_resolved_pct": auto_resolved_pct,
        "avg_triage_seconds": avg_triage_seconds,
        "growth_velocity": growth_velocity,
        "ingestion_success_rate": ingestion_success_rate,
    }


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
    metrics = await _build_metrics(request)
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
        "metrics": metrics,
    }


@router.get("/timeseries")
async def timeseries(
    request: Request,
    metric: str = Query(...),
    window: int = Query(24, ge=1, le=168),
    bucket: str = Query("hour"),
):
    """Generic derived timeseries (ADR0039), zero-filled full bucket axis.

    metric ∈ {signal_velocity (items created), throughput (items completed)};
    bucket ∈ {hour, day}. Empty buckets are emitted as count:0, never omitted.
    """
    if metric not in _TIMESERIES_METRICS or bucket not in _TIMESERIES_BUCKETS:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="invalid metric or bucket")
    stores = request.app.state.stores
    if metric == "signal_velocity":
        rows = await stores.items.created_timeseries(window, bucket)
    else:  # throughput
        rows = await stores.items.completed_timeseries(window, bucket)
    return _zero_filled(rows, window, bucket)


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
