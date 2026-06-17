from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "InteractionEntry",
    "PreferenceSummary",
    "Fact",
    "EntityKnowledge",
    "Relationship",
    "SystemAction",
    "UserTodo",
    "InterpretedResponse",
]


class InteractionEntry(BaseModel):
    id: int | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_type: str
    item_id: int | None = None
    item_summary: str
    triage_card_full: dict = Field(default_factory=dict)
    enrichment_context: dict = Field(default_factory=dict)
    options_presented: list[dict] = Field(default_factory=list)
    option_chosen: str = ""
    choice_index: int | None = None
    todo_created: dict | None = None
    enrichment_depth: str = "none"
    enrichment_calls: int = 0
    enrichment_time_ms: int = 0
    type: str | None = None
    interpreted: dict | None = None
    confirmed: bool | None = None


class PreferenceSummary(BaseModel):
    content: str
    cursor_position: int
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Fact(BaseModel):
    id: str | None = None
    content: str
    source: str = ""
    timestamp: datetime | None = None


class EntityKnowledge(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict = Field(default_factory=dict)


class Relationship(BaseModel):
    from_entity: str
    to_entity: str
    relation: str


class SystemAction(BaseModel):
    action: str
    details: dict = Field(default_factory=dict)


class UserTodo(BaseModel):
    summary: str
    action_category: str


class InterpretedResponse(BaseModel):
    system_actions: list[SystemAction] = Field(default_factory=list)
    user_todos: list[UserTodo] = Field(default_factory=list)
    explanation: str = ""
