from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "EnrichmentTrace",
    "TraceFilters",
    "EnrichmentBudget",
    "EnricherConfig",
    "LoopBackConfig",
]


class EnrichmentTrace(BaseModel):
    id: int | None = None
    item_id: int
    depth: str
    calls_made: int
    time_ms: int
    context_retrieved: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TraceFilters(BaseModel):
    item_id: int | None = None
    since: datetime | None = None


class EnrichmentBudget(BaseModel):
    max_api_calls: int = 3
    max_seconds: int = 10


class EnricherConfig(BaseModel):
    """Configuration for an enrichment stage in the pipeline."""

    id: int | None = None
    name: str
    stage: str  # e.g. "context", "summary", "risk"
    provider: str
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    order_index: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LoopBackConfig(BaseModel):
    """Configuration for a loopback (re-processing) stage."""

    id: int | None = None
    name: str
    trigger: str  # condition that triggers re-processing
    target_stage: str  # which stage to loop back to
    max_iterations: int = 3
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
