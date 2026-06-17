from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "FeedbackCorrection",
    "FilterTuningTask",
]


class FeedbackCorrection(BaseModel):
    """A user override on a single item's filter/enrichment outcome."""

    id: int | None = None
    item_id: int
    rule_id: int | None = None
    original_action: str
    corrected_action: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FilterTuningTask(BaseModel):
    """A pending filter prompt refinement derived from feedback corrections."""

    id: int | None = None
    rule_id: int
    proposed_prompt: str
    correction_ids: list[int] = Field(default_factory=list)
    status: str = "open"  # open, applied, dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
