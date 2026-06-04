from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from pydantic import BaseModel

logger = logging.getLogger(__name__)

CREATE_PENDING_INGESTIONS = """
CREATE TABLE IF NOT EXISTS pending_ingestions (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    type TEXT NOT NULL DEFAULT 'triage',
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_ENTITIES = """
CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    facts JSONB NOT NULL DEFAULT '{}',
    graph_uuid TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, entity_id)
)
"""

CREATE_ENTITY_IDENTITIES = """
CREATE TABLE IF NOT EXISTS entity_identities (
    entity_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    resolved_by TEXT NOT NULL DEFAULT 'heuristic',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, source_id)
)
"""

CREATE_ENTITY_IDENTITIES_IDX = """
CREATE INDEX IF NOT EXISTS idx_entity_identities_canonical
ON entity_identities(entity_type, canonical_id)
"""


class PendingIngestionStore:
    def __init__(self, dsn: str, max_attempts: int = 3):
        self.dsn = dsn
        self.max_attempts = max_attempts
        self.pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(CREATE_PENDING_INGESTIONS)
        await self.pool.execute(CREATE_ENTITIES)
        await self.pool.execute(CREATE_ENTITY_IDENTITIES)
        await self.pool.execute(CREATE_ENTITY_IDENTITIES_IDX)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def enqueue(self, request: BaseModel, entry_type: str = "triage") -> str:
        entry_id = str(uuid.uuid4())
        payload = request.model_dump_json()
        await self.pool.execute(
            "INSERT INTO pending_ingestions (id, payload, type, max_attempts) VALUES ($1, $2::jsonb, $3, $4)",
            entry_id, payload, entry_type, self.max_attempts,
        )
        return entry_id

    async def dequeue(self, limit: int = 1) -> list[dict]:
        rows = await self.pool.fetch(
            """
            UPDATE pending_ingestions
            SET status = 'processing', updated_at = NOW()
            WHERE id IN (
                SELECT id FROM pending_ingestions
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, payload, attempt, type
            """,
            limit,
        )
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempt": r["attempt"], "type": r["type"]} for r in rows]

    async def mark_completed(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE pending_ingestions SET status = 'completed', updated_at = NOW() WHERE id = $1",
            entry_id,
        )

    async def mark_failed(self, entry_id: str, error: str) -> None:
        row = await self.pool.fetchrow(
            "SELECT attempt, max_attempts FROM pending_ingestions WHERE id = $1",
            entry_id,
        )
        if row:
            new_attempt = row["attempt"] + 1
            if new_attempt >= row["max_attempts"]:
                status = "dead_letter"
            else:
                status = "queued"
            await self.pool.execute(
                "UPDATE pending_ingestions SET status = $1, attempt = $2, error = $3, updated_at = NOW() WHERE id = $4",
                status, new_attempt, error, entry_id,
            )

    async def get_dead_letters(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT id, payload, attempt, error, created_at FROM pending_ingestions WHERE status = 'dead_letter' ORDER BY created_at"
        )
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempt": r["attempt"], "error": r["error"]} for r in rows]

    async def queue_depth(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as count FROM pending_ingestions WHERE status = 'queued'"
        )
        return row["count"]

    async def recover_stuck(self) -> int:
        result = await self.pool.execute(
            "UPDATE pending_ingestions SET status = 'queued', updated_at = NOW() WHERE status = 'processing'"
        )
        count = int(result.split()[-1])
        if count:
            logger.info("Recovered %d stuck ingestion entries", count)
        return count

    async def dead_letter_count(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as count FROM pending_ingestions WHERE status = 'dead_letter'"
        )
        return row["count"]

    # --- Entity CRUD ---

    async def upsert_entity(self, entity_type: str, entity_id: str, facts: dict) -> None:
        facts_json = json.dumps(facts)
        await self.pool.execute(
            """
            INSERT INTO entities (entity_type, entity_id, facts)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (entity_type, entity_id)
            DO UPDATE SET facts = entities.facts || $3::jsonb, updated_at = NOW()
            """,
            entity_type, entity_id, facts_json,
        )

    async def get_entity(self, entity_type: str, entity_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT entity_type, entity_id, facts, graph_uuid FROM entities WHERE entity_type = $1 AND entity_id = $2",
            entity_type, entity_id,
        )
        if row is None:
            return None
        return {
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "facts": json.loads(row["facts"]),
            "graph_uuid": row["graph_uuid"],
        }

    async def update_graph_uuid(self, entity_type: str, entity_id: str, graph_uuid: str) -> None:
        await self.pool.execute(
            "UPDATE entities SET graph_uuid = $1, updated_at = NOW() WHERE entity_type = $2 AND entity_id = $3",
            graph_uuid, entity_type, entity_id,
        )

    async def clear_all_graph_uuids(self) -> None:
        await self.pool.execute(
            "UPDATE entities SET graph_uuid = NULL, updated_at = NOW()"
        )

    # --- Identity Resolution ---

    async def resolve_identity(
        self, entity_type: str, source_id: str, facts: dict
    ) -> str:
        """Resolve source_id to a canonical entity ID using signal-tiered matching.

        Returns the canonical_id (which may be source_id itself if no match found).
        """
        from memory.models import (
            STRONG_SIGNAL_KEYS, MEDIUM_SIGNAL_KEYS, WEAK_SIGNAL_KEYS,
            SIGNAL_SCORES, MERGE_THRESHOLD,
        )

        # Check if we already have a mapping for this source_id
        existing = await self.pool.fetchrow(
            "SELECT canonical_id FROM entity_identities "
            "WHERE entity_type = $1 AND source_id = $2",
            entity_type, source_id,
        )
        if existing:
            return existing["canonical_id"]

        # Search for matches among existing entities of the same type
        existing_entities = await self.pool.fetch(
            "SELECT entity_id, facts FROM entities WHERE entity_type = $1",
            entity_type,
        )

        best_canonical = None
        best_score = 0

        for row in existing_entities:
            existing_facts = row["facts"]
            if isinstance(existing_facts, str):
                existing_facts = json.loads(existing_facts)

            score = 0
            for key in STRONG_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["strong"]

            for key in MEDIUM_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["medium"]

            for key in WEAK_SIGNAL_KEYS:
                if (
                    key in facts
                    and key in existing_facts
                    and facts[key]
                    and existing_facts[key]
                    and facts[key] == existing_facts[key]
                ):
                    score += SIGNAL_SCORES["weak"]

            if score > best_score:
                best_score = score
                best_canonical = row["entity_id"]

        if best_score >= MERGE_THRESHOLD and best_canonical:
            canonical_id = best_canonical
        else:
            canonical_id = source_id

        # Insert the identity mapping (ON CONFLICT DO NOTHING for idempotency)
        await self.pool.execute(
            """
            INSERT INTO entity_identities (entity_type, source_id, canonical_id, resolved_by)
            VALUES ($1, $2, $3, 'heuristic')
            ON CONFLICT (entity_type, source_id) DO NOTHING
            """,
            entity_type, source_id, canonical_id,
        )

        return canonical_id

    async def get_canonical(
        self, entity_type: str, source_id: str
    ) -> str | None:
        """Look up the canonical ID for a source_id, or None if not mapped."""
        row = await self.pool.fetchrow(
            "SELECT canonical_id FROM entity_identities "
            "WHERE entity_type = $1 AND source_id = $2",
            entity_type, source_id,
        )
        return row["canonical_id"] if row else None

    async def get_entity_resolved(
        self, entity_type: str, entity_id: str
    ) -> dict | None:
        """Get entity, resolving through identity mapping first."""
        canonical = await self.get_canonical(entity_type, entity_id)
        target_id = canonical or entity_id
        return await self.get_entity(entity_type, target_id)
