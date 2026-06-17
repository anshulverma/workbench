from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "Plan",
    "PlanFilters",
    "PlanUpdate",
]


class Plan(BaseModel):
    id: int | None = None
    title: str
    status: str = "draft"
    content: str = ""
    sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PlanFilters(BaseModel):
    status: str | None = None


class PlanUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    content: str | None = None
