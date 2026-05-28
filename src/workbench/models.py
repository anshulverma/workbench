# server/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
import uuid

class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    PENDING = "pending"

class ItemStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"
    ARCHIVED = "archived"

class ItemCategory(str, Enum):
    ACTION_ITEM = "action_item"
    MEETING = "meeting"
    INFORMATIONAL = "informational"

class ItemOrigin(str, Enum):
    AUTO_INCLUDED = "auto_included"
    TRIAGED = "triaged"
    MANUAL = "manual"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobTrigger(str, Enum):
    MANUAL = "manual"
    POLL = "poll"

class RawItem(BaseModel):
    id: str
    source_type: str
    source_label: str
    raw_text: str

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

class ItemUpdate(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    summary: str | None = None

class ItemFilters(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    source_type: str | None = None
    category: ItemCategory | None = None

class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)

class TriageCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str | None = None
    card_content: dict = Field(default_factory=dict)
    options: list[TriageOption] = Field(default_factory=list)
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    response: str | None = None

class TriageResponse(BaseModel):
    card_id: str
    choice: int
    raw_text: str | None = None

class FilterRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str | None = None
    pattern: str
    action: str  # "include" or "drop"
    priority: Priority | None = None
    created_from_interaction_id: str | None = None

class InteractionEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_type: str
    item_id: str | None = None
    item_summary: str
    triage_card_full: dict = Field(default_factory=dict)
    enrichment_context: dict = Field(default_factory=dict)
    options_presented: list[dict] = Field(default_factory=list)
    option_chosen: str = ""
    todo_created: dict | None = None
    enrichment_depth: str = "none"
    enrichment_calls: int = 0
    enrichment_time_ms: int = 0

class EnrichmentTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    depth: str
    calls_made: int
    time_ms: int
    context_retrieved: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TraceFilters(BaseModel):
    item_id: str | None = None
    since: datetime | None = None

class SourceConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    adapter_type: str
    config: dict = Field(default_factory=dict)
    schedule: str = "*/15 * * * *"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SourceConfigUpdate(BaseModel):
    config: dict | None = None
    schedule: str | None = None
    enabled: bool | None = None

class PipelineJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger: JobTrigger
    status: JobStatus = JobStatus.PENDING
    input_hash: str = ""
    items_extracted: int = 0
    items_included: int = 0
    items_triaged: int = 0
    items_dropped: int = 0
    items_failed: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

class Plan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
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

class PreferenceSummary(BaseModel):
    content: str
    cursor_position: int
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class EnrichmentBudget(BaseModel):
    max_api_calls: int = 3
    max_seconds: int = 10

class Fact(BaseModel):
    content: str
    source: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class EntityKnowledge(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict = Field(default_factory=dict)

class Relationship(BaseModel):
    from_entity: str
    to_entity: str
    relation: str
