"""Enrichers API — list configured enrichment stages and their samples.

GET /api/enrichers                      — list all enricher configs
GET /api/enrichers/{enricher_id}        — get single enricher
GET /api/enrichers/{enricher_id}/samples — enrichment trace samples for an enricher
"""

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["enrichers"])


def _get_enrichers_store(request: Request):
    stores = request.app.state.stores
    if stores.enrichers is None:
        raise HTTPException(503, "Enrichers store not configured")
    return stores.enrichers


@router.get("/enrichers")
async def list_enrichers(request: Request):
    store = _get_enrichers_store(request)
    return await store.get_enrichers()


@router.get("/enrichers/{enricher_id}")
async def get_enricher(enricher_id: str, request: Request):
    store = _get_enrichers_store(request)
    enricher = await store.get_enricher(enricher_id)
    if not enricher:
        raise HTTPException(404, "Enricher not found")
    return enricher


@router.get("/enrichers/{enricher_id}/samples")
async def get_enricher_samples(
    enricher_id: str,
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    """Return enrichment trace entries for items processed by this enricher.

    Uses the enrichment trace store filtered by the enricher's stage name.
    """
    enrichers_store = _get_enrichers_store(request)
    enricher = await enrichers_store.get_enricher(enricher_id)
    if not enricher:
        raise HTTPException(404, "Enricher not found")

    stores = request.app.state.stores
    from workbench.domain import TraceFilters

    traces = await stores.enrichment.get_traces(TraceFilters())
    # Filter traces by the enricher's stage (depth field matches stage)
    samples = [t for t in traces if t.depth == enricher.stage][:limit]
    return samples
