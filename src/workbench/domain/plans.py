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
    # Lineage stub: the item path(s) this plan was built from. The future Plan
    # creation site links in one line: record("plan", plan.id, plan.item_paths).
    # Not persisted yet (no plans schema column); carried in-memory for the
    # linkage contract (ADR 0063 §Out of Scope).
    item_paths: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PlanFilters(BaseModel):
    status: str | None = None


class PlanUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    content: str | None = None
