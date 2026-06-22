"""LLM usage tracking API.

GET  /api/llm/calls              — list LLM calls (summary view)
GET  /api/llm/calls/{call_id}    — single call detail (prompt + subcalls)
GET  /api/llm/metrics             — 24h metrics summary
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _store(request: Request):
    """503 guard: raise HTTPException(503) when llm_calls store is unconfigured."""
    stores = request.app.state.stores
    if stores.llm_calls is None:
        raise HTTPException(503, "LLM call store not configured")
    return stores.llm_calls


def _llm_call_view(rec) -> dict:
    """Map LlmCallRecord to the UI list-view JSON shape (no prompt/subcalls)."""
    return {
        "id": f"llm_{rec.id}",
        "ts": rec.started_at.isoformat(),
        "origin": rec.origin,
        "purpose": rec.purpose,
        "stage": rec.stage,
        "model": rec.model,
        "temperature": rec.temperature if rec.temperature is not None else 0.0,
        "status": rec.status,
        "batch": rec.batch,
        "items": rec.items,
        "tokens_in": rec.tokens_in,
        "tokens_out": rec.tokens_out,
        "latency_ms": rec.latency_ms,
    }


def _detail_view(rec, linked_items: list[dict]) -> dict:
    """Map LlmCallRecord to the detail-view JSON shape (prompt + subcalls)."""
    return {
        "sysPrompt": rec.system_prompt or "",
        "subcalls": [s.model_dump() for s in rec.subcalls],
        "linked_items": linked_items,
    }


@router.get("/calls")
async def list_calls(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    origin: str | None = None,
    q: str | None = None,
):
    """List LLM calls in summary view (no prompt/completion/subcalls)."""
    store = _store(request)

    # Parse before cursor: format is "<iso_ts>,<id>"
    before_parsed = None
    if before:
        parts = before.rsplit(",", 1)
        if len(parts) == 2:
            ts_str, id_str = parts
            try:
                ts = datetime.fromisoformat(ts_str)
                call_id = int(id_str)
                before_parsed = (ts, call_id)
            except (ValueError, TypeError):
                # Malformed cursor: ignore it
                pass

    records = await store.list_calls(
        limit=limit,
        before=before_parsed,
        stage=stage,
        status=status,
        origin=origin,
        q=q,
    )

    return [_llm_call_view(rec) for rec in records]


@router.get("/calls/{call_id}")
async def get_call_detail(call_id: str, request: Request):
    """Get a single LLM call's detail (prompt + subcalls)."""
    store = _store(request)

    # call_id format is "llm_{id}"
    if not call_id.startswith("llm_"):
        raise HTTPException(404, "Call not found")

    try:
        numeric_id = int(call_id[4:])
    except (ValueError, TypeError):
        raise HTTPException(404, "Call not found")

    rec = await store.get_by_id(numeric_id)
    if rec is None:
        raise HTTPException(404, "Call not found")

    links = await request.app.state.stores.entity_links.linked_items_for_correlation(
        rec.correlation_id
    )
    linked_items = [
        {"id": li.id, "path": li.path, "summary": li.summary} for li in links
    ]
    return _detail_view(rec, linked_items)


@router.get("/metrics")
async def get_metrics(request: Request):
    """24h LLM usage metrics."""
    store = _store(request)

    metrics = await store.metrics_24h()
    now = datetime.now(timezone.utc)

    return {
        **metrics,
        "window_hours": 24,
        "as_of": now.isoformat(),
    }
