from fastapi import APIRouter, Request
from server.models import FilterRule

router = APIRouter(prefix="/api", tags=["filter_rules"])


@router.get("/filter-rules")
async def list_rules(request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.get_rules()


@router.post("/filter-rules")
async def add_rule(rule: FilterRule, request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.add_rule(rule)


@router.get("/filter-rules/{source_type}")
async def get_source_rules(source_type: str, request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.get_source_rules(source_type)
