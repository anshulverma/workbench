"""Recent activity feed (Design Section 3).

Promotes the recent-items slice out of /api/debug/pipeline into a first-class,
bearer-authed endpoint. The debug route stays for backward compatibility.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, Request

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/activity")
async def activity(request: Request, limit: int = Query(50, ge=1, le=200)):
    """Most recent items as a flat activity feed."""
    stores = request.app.state.stores
    try:
        items = await stores.items.items_recent(limit=limit)
    except Exception:
        logger.warning("activity_query_failed")
        return []
    return [
        {
            "id": i.id,
            "status": i.status.value,
            "source_type": i.source_type,
            "summary": i.summary,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in items
    ]
