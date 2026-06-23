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
    filter_id: str | None = None
    item_summary: str | None = None
    original_action: str
    corrected_action: str
    from_label: str | None = None
    to_label: str | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FilterTuningTask(BaseModel):
    """A pending filter prompt refinement derived from feedback corrections."""

    id: int | None = None
    rule_id: int | None = None  # was required int; now optional (key by filter_id)
    filter_id: str | None = None
    item_id: int | None = None
    item_summary: str | None = None
    from_outcome: str | None = None
    to_outcome: str | None = None
    from_label: str | None = None
    to_label: str | None = None
    filter_prompt: str | None = None
    proposed_prompt: str
    kind: str | None = None
    correction_ids: list[int] = Field(default_factory=list)
    status: str = "open"  # open, applied, dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
