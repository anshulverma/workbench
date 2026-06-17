from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from workbench.domain import FilterRule

router = APIRouter(prefix="/api", tags=["filter_rules"])


@router.get("/filter-rules")
async def list_rules(request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.get_rules()


@router.post("/filter-rules")
async def add_rule(rule: FilterRule, request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.add_rule(rule)


@router.get("/filter-rules/{rule_id}")
async def get_source_rules(rule_id: str, request: Request):
    stores = request.app.state.stores
    return await stores.filter_rules.get_source_rules(rule_id)


@router.patch("/filter-rules/{rule_id}")
async def update_rule(rule_id: int, updates: dict, request: Request):
    stores = request.app.state.stores
    try:
        return await stores.filter_rules.update_rule(rule_id, updates)
    except Exception:
        raise HTTPException(404, "Filter rule not found")


@router.delete("/filter-rules/{rule_id}")
async def delete_rule(rule_id: int, request: Request):
    stores = request.app.state.stores
    await stores.filter_rules.delete_rule(rule_id)
    return {"status": "deleted"}


class PromptUpdate(BaseModel):
    prompt: str


@router.patch("/filter-rules/{rule_id}/prompt")
async def update_rule_prompt(rule_id: int, body: PromptUpdate, request: Request):
    stores = request.app.state.stores
    try:
        return await stores.filter_rules.update_rule(rule_id, {"prompt": body.prompt})
    except Exception:
        raise HTTPException(404, "Filter rule not found")
