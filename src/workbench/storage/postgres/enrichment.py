from __future__ import annotations

import json

import asyncpg

from workbench.models import EnrichmentTrace, TraceFilters
from workbench.storage.base import EnrichmentTraceStore


class PgEnrichmentTraceStore(EnrichmentTraceStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def log_trace(self, trace: EnrichmentTrace) -> None:
        await self.pool.execute(
            """INSERT INTO enrichment_trace
               (id, item_id, depth, calls_made, time_ms,
                context_retrieved, timestamp)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)""",
            trace.id,
            trace.item_id,
            trace.depth,
            trace.calls_made,
            trace.time_ms,
            json.dumps(trace.context_retrieved),
            trace.timestamp,
        )

    async def get_traces(self, filters: TraceFilters) -> list[EnrichmentTrace]:
        query = "SELECT * FROM enrichment_trace WHERE 1=1"
        params: list = []
        idx = 1
        if filters.item_id:
            query += f" AND item_id = ${idx}"
            params.append(filters.item_id)
            idx += 1
        if filters.since:
            query += f" AND timestamp >= ${idx}"
            params.append(filters.since)
            idx += 1
        query += " ORDER BY timestamp DESC"
        rows = await self.pool.fetch(query, *params)
        return [self._row_to_trace(r) for r in rows]

    @staticmethod
    def _row_to_trace(row: asyncpg.Record) -> EnrichmentTrace:
        ctx = row["context_retrieved"]
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        return EnrichmentTrace(
            id=row["id"],
            item_id=row["item_id"],
            depth=row["depth"],
            calls_made=row["calls_made"],
            time_ms=row["time_ms"],
            context_retrieved=ctx,
            timestamp=row["timestamp"],
        )
