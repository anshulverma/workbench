from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from workbench.domain.enums import JobStatus, JobTrigger, QueueEntryStatus

__all__ = [
    "PipelineJob",
    "IngestionQueueEntry",
    "IngestionRun",
]


class PipelineJob(BaseModel):
    id: int | None = None
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


class IngestionQueueEntry(BaseModel):
    id: int | None = None
    raw_content: str
    source_type: str
    source_id: str | None = None
    urgency_signals: dict[str, Any] = Field(default_factory=dict)
    urgency_score: int = 50
    job_id: int
    status: QueueEntryStatus = QueueEntryStatus.QUEUED
    attempt: int = 0
    max_attempts: int = 3
    next_retry_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IngestionRun(BaseModel):
    id: int | None = None
    source_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "running"  # running | success | error
    raw_enqueued: int = 0
    error: str | None = None
