from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "DiffMetadata",
    "DiffRisk",
    "DiffHunkSection",
    "DiffCardContent",
]


class DiffMetadata(BaseModel):
    author: str
    team: str | None = None
    status: str


class DiffRisk(BaseModel):
    factors: list[str] = Field(default_factory=list)
    watch_outs: list[str] = Field(default_factory=list)


class DiffHunkSection(BaseModel):
    file: str
    header: str
    code: str
    annotation: str = ""
    expandable: bool = True
    rank: int = 0


class DiffCardContent(BaseModel):
    metadata: DiffMetadata
    summary: str
    risk: DiffRisk
    why_care: str
    hunks: list[DiffHunkSection] = Field(default_factory=list)
