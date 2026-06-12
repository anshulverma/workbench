from __future__ import annotations

import uuid
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


class ExtractedItem(BaseModel):
    summary: str
    category: ItemCategory
    source_context: str
    raw_item: RawItem


class Item(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
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
    parent_item_id: str | None = None
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
