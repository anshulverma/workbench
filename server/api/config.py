from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["config"])


class ConfigPatch(BaseModel):
    updates: dict[str, str]


@router.get("/config")
async def get_config(request: Request):
    stores = request.app.state.stores
    return await stores.config.get_all()


@router.patch("/config")
async def patch_config(patch: ConfigPatch, request: Request):
    stores = request.app.state.stores
    for key, value in patch.updates.items():
        await stores.config.set(key, value)
    return await stores.config.get_all()
