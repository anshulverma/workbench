from fastapi import APIRouter, HTTPException, Request
from workbench.models import ItemFilters, ItemUpdate

router = APIRouter(prefix="/api", tags=["items"])


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


@router.patch("/items/{item_id}")
async def update_item(item_id: str, updates: ItemUpdate, request: Request):
    stores = request.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return await stores.items.update_item(item_id, updates)


@router.delete("/items/{item_id}")
async def archive_item(item_id: str, request: Request):
    stores = request.app.state.stores
    await stores.items.archive_item(item_id)
    return {"status": "archived"}
