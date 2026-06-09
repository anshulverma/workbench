from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from workbench.domain.enums import Priority

__all__ = [
    "FilterRule",
]


class FilterRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str | None = None
    pattern: str
    action: str  # "include" or "drop"
    priority: Priority | None = None
    created_from_interaction_id: str | None = None
