from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "FeedbackCorrection",
    "FilterTuningTask",
]


class FeedbackCorrection(BaseModel):
    """A user override on a single item's filter/enrichment outcome."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    rule_id: str | None = None
    original_action: str
    corrected_action: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FilterTuningTask(BaseModel):
    """A pending filter prompt refinement derived from feedback corrections."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    proposed_prompt: str
    correction_ids: list[str] = Field(default_factory=list)
    status: str = "open"  # open, applied, dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
