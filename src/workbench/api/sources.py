from fastapi import APIRouter, HTTPException, Request
from workbench.models import SourceConfigUpdate

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources")
async def list_sources(request: Request):
    stores = request.app.state.stores
    return await stores.sources.get_sources()


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, updates: SourceConfigUpdate, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return await stores.sources.update_source(source_id, updates)
