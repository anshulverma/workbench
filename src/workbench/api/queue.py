from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("/dead-letter")
async def get_dead_letters(request: Request):
    stores = request.app.state.stores
    entries = await stores.ingestion_queue.get_dead_letters()
    return [e.model_dump() for e in entries]


@router.post("/dead-letter/{entry_id}/retry")
async def retry_dead_letter(entry_id: str, request: Request):
    stores = request.app.state.stores
    entries = await stores.ingestion_queue.get_dead_letters()
    if not any(e.id == entry_id for e in entries):
        raise HTTPException(404, "Dead letter entry not found")
    await stores.ingestion_queue.retry_dead_letter(entry_id)
    return {"status": "requeued"}


@router.delete("/dead-letter/{entry_id}")
async def purge_dead_letter(entry_id: str, request: Request):
    stores = request.app.state.stores
    await stores.ingestion_queue.purge_dead_letter(entry_id)
    return {"status": "purged"}
