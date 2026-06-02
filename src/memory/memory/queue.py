from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from memory.models import TriageRecordRequest

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pending_ingestions (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class PendingIngestionStore:
    def __init__(self, dsn: str, max_attempts: int = 3):
        self.dsn = dsn
        self.max_attempts = max_attempts
        self.pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(CREATE_TABLE)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def enqueue(self, request: TriageRecordRequest) -> str:
        entry_id = str(uuid.uuid4())
        payload = request.model_dump_json()
        await self.pool.execute(
            "INSERT INTO pending_ingestions (id, payload, max_attempts) VALUES ($1, $2::jsonb, $3)",
            entry_id, payload, self.max_attempts,
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
            RETURNING id, payload, attempt
            """,
            limit,
        )
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempt": r["attempt"]} for r in rows]

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
