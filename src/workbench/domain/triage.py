from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

__all__ = [
    "TriageOption",
    "TriageCard",
    "TriageResponse",
    "TriageResponseResult",
    "CardLink",
    "CardSection",
    "ThreadHunk",
    "CardMessage",
    "ChangeContext",
]


class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)
    suggested: bool = False
    suggestion_reason: str | None = None


class CardLink(BaseModel):
    label: str
    url: str


class CardSection(BaseModel):
    title: str
    body: str
    monospace: bool = False


class ThreadHunk(BaseModel):
    file: str
    header: str
    code: str
    rank: int = 0


class CardMessage(BaseModel):
    header: str
    sections: list[CardSection] = Field(default_factory=list)
    links: list[CardLink] = Field(default_factory=list)
    options: list[TriageOption] = Field(default_factory=list)
    thread_hunks: list[ThreadHunk] = Field(default_factory=list)


class ChangeContext(BaseModel):
    change_type: str
    changed_fields: dict[str, dict[str, str]] = Field(default_factory=dict)
    change_summary: str
    previous_triage_action: str | None = None
    previous_priority: str | None = None


class TriageCard(BaseModel):
    # DB-assigned autoincrement id; None until persisted (save_card sets it).
    id: int | None = None
    item_id: int | None = None
    card_content: dict = Field(default_factory=dict)
    options: list[TriageOption] = Field(default_factory=list)
    relevance_score: int = 50
    confidence_score: int = 50
    status: str = "queued"  # queued, sent, responded, expired
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bot_message_id: str | None = None
    thread_name: str | None = None
    daily_sequence: int | None = None
    expires_at: datetime | None = None
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    response: str | None = None
    deferred_until: datetime | None = None


class TriageResponse(BaseModel):
    card_id: int
    choice: int | None = None
    raw_text: str | None = None


class TriageResponseResult(BaseModel):
    status: str
    action: str | None = None
    system_actions_executed: list[str] = Field(default_factory=list)
    user_todos_created: list[str] = Field(default_factory=list)
    explanation: str = ""
