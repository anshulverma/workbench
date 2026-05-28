from fastapi import APIRouter, Request
from workbench import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    stores = request.app.state.stores
    result = {"status": "ok", "version": __version__}

    try:
        depth = await stores.ingestion_queue.queue_depth()
        pending = await stores.triage.get_pending()
        dead = await stores.ingestion_queue.get_dead_letters()
        result["queue"] = {
            "ingestion_depth": depth,
            "triage_pending": len(pending),
            "dead_letters": len(dead),
        }
    except Exception:
        result["status"] = "degraded"
        result["error"] = "storage unavailable"

    return result
