from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from workbench.domain.enums import ItemCategory, ItemOrigin, ItemStatus, Priority

__all__ = [
    "RawItem",
    "ExtractedItem",
    "Item",
    "ItemUpdate",
    "ItemFilters",
]


class RawItem(BaseModel):
    id: str
    source_type: str
    source_label: str
    raw_text: str
    urgency_signals: dict[str, Any] = Field(default_factory=dict)
    # Source identity for "open in source" links. `source_ref` is the stable,
    # human-readable id (e.g. "D123456", "T123", "#42"); `source_url` is the
    # canonical external URL. Both are adapter-populated and optional — adapters
    # with no meaningful URL leave them None and the UI omits the link.
    source_ref: str | None = None
    source_url: str | None = None


class ExtractedItem(BaseModel):
    summary: str
    category: ItemCategory
    source_context: str
    raw_item: RawItem


class Item(BaseModel):
    # DB-assigned autoincrement id; None until persisted (save_item sets it).
    id: int | None = None
    source_type: str
    source_id: str
    summary: str
    category: ItemCategory
    origin: ItemOrigin
    priority: Priority
    status: ItemStatus = ItemStatus.ACTIVE
    raw_data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    parent_item_id: int | None = None
    action_source: str | None = None
    action_category: str | None = None
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    llm_summary: str | None = None
    enriched_context: dict = Field(default_factory=dict)
    funnel_log: list[dict] = Field(default_factory=list)
    verdict_action: str | None = None
    verdict_priority: str | None = None
    verdict_confidence: int | None = None


class ItemUpdate(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    summary: str | None = None


class ItemFilters(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    source_type: str | None = None
    category: ItemCategory | None = None
