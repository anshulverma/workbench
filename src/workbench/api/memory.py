from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["memory"])

# Manual facts carry a distinct origin marker that coexists with learned facts
# and ADR0019 tombstones; the synthesis pipeline does not overwrite them (ADR0045).
MANUAL_FACT_ORIGIN = "manual"


@router.get("/memory/facts")
async def get_facts(request: Request):
    """Returns the facts envelope {available, memory_type, facts}.

    Always 200. Three empty states the Knowledge page distinguishes:
    - noop: available=false, memory_type="noop"
    - configured-but-down: available=false, memory_type="http"/"zep"
    - configured-and-empty: available=true, facts=[]
    """
    memory = request.app.state.memory
    memory_type = getattr(memory, "memory_type", "unknown")
    try:
        available = await memory.is_available()
    except Exception:
        available = False
    facts = []
    if available:
        try:
            facts = await memory.list_facts()
        except Exception:
            logger.warning("memory.list_facts failed", memory_type=memory_type)
            facts = []
    return {
        "available": available,
        "memory_type": memory_type,
        "facts": [f.model_dump(mode="json") for f in facts],
    }


class FactCreateBody(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def content_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content must not be empty")
        return v.strip()


@router.post("/memory/facts")
async def create_fact(body: FactCreateBody, request: Request):
    """Creates a manual Preference Fact with a distinct 'manual' origin.

    Manual facts coexist with learned facts and ADR0019 tombstones; the
    synthesis pipeline does not overwrite them (ADR0045). Returns the created
    Fact. Under NoopMemoryLayer -> 501 (consistent with delete/update).
    """
    memory = request.app.state.memory
    try:
        fact = await memory.add_fact(body.content, MANUAL_FACT_ORIGIN)
    except NotImplementedError:
        raise HTTPException(501, "memory layer not configured")
    logger.info("manual fact created", fact_id=fact.id, source=fact.source)
    return fact.model_dump(mode="json")


@router.delete("/memory/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request):
    memory = request.app.state.memory
    try:
        await memory.delete_fact(fact_id)
    except NotImplementedError:
        raise HTTPException(501, "memory layer not configured")
    logger.info("fact deleted", fact_id=fact_id)
    return {"status": "deleted"}


class FactPatchBody(BaseModel):
    content: str


@router.patch("/memory/facts/{fact_id}")
async def update_fact(fact_id: str, body: FactPatchBody, request: Request):
    memory = request.app.state.memory
    try:
        await memory.update_fact(fact_id, body.content)
    except NotImplementedError:
        raise HTTPException(501, "memory layer not configured")
    logger.info("fact updated", fact_id=fact_id)
    return {"status": "updated"}
