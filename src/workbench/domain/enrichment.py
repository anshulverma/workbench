from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "EnrichmentTrace",
    "TraceFilters",
    "EnrichmentBudget",
]


class EnrichmentTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    depth: str
    calls_made: int
    time_ms: int
    context_retrieved: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TraceFilters(BaseModel):
    item_id: str | None = None
    since: datetime | None = None


class EnrichmentBudget(BaseModel):
    max_api_calls: int = 3
    max_seconds: int = 10
