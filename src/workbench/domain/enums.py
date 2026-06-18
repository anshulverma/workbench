from __future__ import annotations

from enum import Enum

__all__ = [
    "Priority",
    "ItemStatus",
    "ItemCategory",
    "ItemOrigin",
    "EntityType",
    "ActionCategory",
    "JobStatus",
    "JobTrigger",
    "QueueEntryStatus",
]


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    PENDING = "pending"


class ItemStatus(str, Enum):
    PENDING_TRIAGE = "pending_triage"
    ACTIVE = "active"
    DONE = "done"
    ARCHIVED = "archived"
    # Auto-dropped by the relevance filter. Persisted (not discarded) so the
    # Ingestion funnel can show what was filtered out and why; excluded from the
    # active/triage feeds, which query by their own statuses.
    DROPPED = "dropped"
    # Lineage lifecycle (D2/D3): a root is born INGESTED at enqueue and moves to
    # EXTRACTED once its depth-1 children exist. Verdict statuses live on the
    # children, not the root.
    INGESTED = "ingested"
    EXTRACTED = "extracted"


class ItemCategory(str, Enum):
    ACTION_ITEM = "action_item"
    MEETING = "meeting"
    PLAN_SEED = "plan_seed"
    INFORMATIONAL = "informational"


class ItemOrigin(str, Enum):
    AUTO_INCLUDED = "auto_included"
    TRIAGED = "triaged"
    MANUAL = "manual"


class EntityType(str, Enum):
    PERSON = "person"
    REPO = "repo"
    TEAM = "team"
    SPACE = "space"
    GROUP = "group"


class ActionCategory(str, Enum):
    DELEGATION = "delegation"
    COMMUNICATION = "communication"
    SCHEDULING = "scheduling"
    REVIEW = "review"
    CREATION = "creation"
    UPDATE = "update"
    DECISION = "decision"
    INVESTIGATION = "investigation"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobTrigger(str, Enum):
    MANUAL = "manual"
    POLL = "poll"


class QueueEntryStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
