from fastapi import APIRouter, HTTPException, Request
from workbench.models import SourceConfig, SourceConfigUpdate

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources")
async def list_sources(request: Request):
    stores = request.app.state.stores
    return await stores.sources.get_sources()


@router.post("/sources")
async def create_source(source: SourceConfig, request: Request):
    stores = request.app.state.stores
    return await stores.sources.save_source(source)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str, updates: SourceConfigUpdate, request: Request
):
    stores = request.app.state.stores
    return await stores.sources.update_source(source_id, updates)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, request: Request):
    stores = request.app.state.stores
    await stores.sources.delete_source(source_id)
    return {"status": "deleted"}
