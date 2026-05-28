from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory/facts")
async def get_facts(request: Request):
    """Returns memory facts. Empty list for Phase 1a (NoopMemoryLayer)."""
    memory = request.app.state.memory
    facts = await memory.query_preferences("")
    return [f.model_dump() for f in facts]
