"""Durable message entity for cross-entity lineage.

A persisted record per outbound/inbound message (card sends, alerts, briefings,
re-triage pings, replies). Makes a message a first-class, linkable entity rather
than an ephemeral render of a TriageCard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["Message"]


class Message(BaseModel):
    id: int | None = None
    kind: Literal["card", "alert", "briefing", "retriage", "reply"]
    direction: Literal["outbound", "inbound"]
    bot_message_id: str | None = None
    body: str | None = None
    summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
