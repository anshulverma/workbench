from __future__ import annotations

import asyncpg

from workbench.storage.base import ProcessedStore


class PgProcessedStore(ProcessedStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def is_processed(self, source_type: str, source_id: str) -> bool:
        row = await self.pool.fetchrow(
            "SELECT 1 FROM processed WHERE source_type = $1 AND source_id = $2",
            source_type,
            source_id,
        )
        return row is not None

    async def mark_processed(self, source_type: str, source_id: str) -> None:
        await self.pool.execute(
            "INSERT INTO processed (source_type, source_id, processed_at) "
            "VALUES ($1, $2, NOW()) ON CONFLICT DO NOTHING",
            source_type,
            source_id,
        )
