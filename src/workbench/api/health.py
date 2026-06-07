from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

from workbench import __version__

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])


async def _check_storage(stores) -> dict:
    try:
        await stores.items.pool.fetchval("SELECT 1")
        return {"status": "healthy"}
    except Exception as e:
        logger.warning("storage_health_check_failed", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


async def _check_connections(connections: dict) -> dict:
    result = {}
    for name, conn in connections.items():
        try:
            healthy = conn.is_healthy()
            result[name] = {"status": "healthy" if healthy else "unhealthy"}
        except Exception as e:
            logger.warning(
                "connection_health_check_failed", connection=name, error=str(e)
            )
            result[name] = {"status": "unhealthy", "error": str(e)}
    return result


async def _build_health(request: Request) -> tuple[dict, bool]:
    stores = request.app.state.stores
    connections = getattr(request.app.state, "connections", {})

    storage_health = await _check_storage(stores)
    connection_health = await _check_connections(connections)

    critical_healthy = storage_health["status"] == "healthy"

    queue_stats = {}
    if critical_healthy:
        try:
            depth = await stores.ingestion_queue.queue_depth()
            pending = await stores.triage.get_pending()
            dead = await stores.ingestion_queue.count_dead_letters()
            queue_stats = {
                "ingestion_depth": depth,
                "triage_pending": len(pending),
                "dead_letters": dead,
            }
        except Exception:
            logger.warning("health_queue_stats_failed")

    return {
        "status": "healthy" if critical_healthy else "unhealthy",
        "version": __version__,
        "components": {
            "storage": storage_health,
            "connections": connection_health,
        },
        "queue": queue_stats,
    }, critical_healthy


@router.get("/health")
async def health(request: Request, response: Response):
    data, healthy = await _build_health(request)
    if not healthy:
        response.status_code = 503
    return data


@router.get("/health/live")
async def liveness():
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response):
    data, healthy = await _build_health(request)
    if not healthy:
        response.status_code = 503
    return data
