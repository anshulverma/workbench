from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import asyncpg

from workbench.models import IngestionQueueEntry, QueueEntryStatus
from workbench.storage.base import IngestionQueueStore


class PgIngestionQueueStore(IngestionQueueStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def enqueue(self, entry: IngestionQueueEntry) -> IngestionQueueEntry:
        await self.pool.execute(
            """INSERT INTO ingestion_queue
               (id, raw_content, source_type, source_id, urgency_signals,
                urgency_score, job_id, status, attempt, max_attempts,
                next_retry_at, error, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10,
                       $11, $12, $13, $14)""",
            entry.id,
            entry.raw_content,
            entry.source_type,
            entry.source_id,
            json.dumps(entry.urgency_signals),
            entry.urgency_score,
            entry.job_id,
            entry.status.value,
            entry.attempt,
            entry.max_attempts,
            entry.next_retry_at,
            entry.error,
            entry.created_at,
            entry.updated_at,
        )
        return entry

    async def dequeue(self, limit: int = 1) -> list[IngestionQueueEntry]:
        rows = await self.pool.fetch(
            """UPDATE ingestion_queue
               SET status = 'processing', updated_at = NOW()
               WHERE id IN (
                   SELECT id FROM ingestion_queue
                   WHERE status = 'queued'
                     AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                   ORDER BY urgency_score DESC
                   LIMIT $1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            limit,
        )
        return [self._row_to_entry(r) for r in rows]

    async def mark_completed(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'completed', updated_at = NOW() "
            "WHERE id = $1",
            entry_id,
        )

    async def mark_failed(self, entry_id: str, error: str) -> None:
        row = await self.pool.fetchrow(
            "SELECT attempt, max_attempts FROM ingestion_queue WHERE id = $1",
            entry_id,
        )
        if row is None:
            return

        attempt = row["attempt"] + 1
        max_attempts = row["max_attempts"]

        if attempt >= max_attempts:
            await self.pool.execute(
                "UPDATE ingestion_queue SET status = 'dead_letter', "
                "attempt = $1, error = $2, updated_at = NOW() WHERE id = $3",
                attempt,
                error,
                entry_id,
            )
        else:
            backoff = timedelta(seconds=(2**attempt) * 5)
            next_retry = datetime.now(timezone.utc) + backoff
            await self.pool.execute(
                "UPDATE ingestion_queue SET status = 'queued', attempt = $1, "
                "error = $2, next_retry_at = $3, updated_at = NOW() WHERE id = $4",
                attempt,
                error,
                next_retry,
                entry_id,
            )

    async def get_dead_letters(self) -> list[IngestionQueueEntry]:
        rows = await self.pool.fetch(
            "SELECT * FROM ingestion_queue WHERE status = 'dead_letter' "
            "ORDER BY updated_at DESC"
        )
        return [self._row_to_entry(r) for r in rows]

    async def retry_dead_letter(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'queued', attempt = 0, "
            "error = NULL, next_retry_at = NULL, updated_at = NOW() "
            "WHERE id = $1 AND status = 'dead_letter'",
            entry_id,
        )

    async def purge_dead_letter(self, entry_id: str) -> None:
        await self.pool.execute(
            "DELETE FROM ingestion_queue WHERE id = $1 AND status = 'dead_letter'",
            entry_id,
        )

    async def recover_stuck(self) -> int:
        result = await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'queued', updated_at = NOW() "
            "WHERE status = 'processing'"
        )
        return int(result.split()[-1])

    async def queue_depth(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM ingestion_queue "
            "WHERE status IN ('queued', 'processing')"
        )
        return row["cnt"]  # type: ignore[index]

    @staticmethod
    def _row_to_entry(row: asyncpg.Record) -> IngestionQueueEntry:
        signals = row["urgency_signals"]
        if isinstance(signals, str):
            signals = json.loads(signals)
        return IngestionQueueEntry(
            id=row["id"],
            raw_content=row["raw_content"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            urgency_signals=signals,
            urgency_score=row["urgency_score"],
            job_id=row["job_id"],
            status=QueueEntryStatus(row["status"]),
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            next_retry_at=row["next_retry_at"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
