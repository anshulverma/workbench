from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Fact(BaseModel):
    content: str
    source: str = "graphiti"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageRecordRequest(BaseModel):
    card: dict
    response: dict


class PreferenceQueryResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    postgres: str
    graphiti: str


class FactsListResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    total: int = 0


class EntityRecordRequest(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict


class DecisionRecordRequest(BaseModel):
    item_summary: str
    decision: str  # "auto_include" or "auto_drop"
    reason: str
    source_type: str = "unknown"


class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict


class RelationshipsResponse(BaseModel):
    relationships: list[dict]  # [{from_entity, to_entity, relation}]


class QueueDepthResponse(BaseModel):
    depth: int
    dead_letters: int


# --- Identity resolution signal tiers ---

STRONG_SIGNAL_KEYS = {"email", "phone", "platform_uid"}
MEDIUM_SIGNAL_KEYS = {"name", "username"}
WEAK_SIGNAL_KEYS = {"first_name", "timezone", "title"}

SIGNAL_SCORES = {
    "strong": 10,
    "medium": 5,
    "weak": 1,
}
MERGE_THRESHOLD = 10
