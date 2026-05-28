import json
from workbench.storage.base import EnrichmentTraceStore
from workbench.models import EnrichmentTrace, TraceFilters


class SqliteEnrichmentTraceStore(EnrichmentTraceStore):
    def __init__(self, db):
        self.db = db

    async def log_trace(self, trace: EnrichmentTrace) -> None:
        await self.db.execute(
            "INSERT INTO enrichment_trace (id, item_id, depth, calls_made, time_ms, context_retrieved, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trace.id,
                trace.item_id,
                trace.depth,
                trace.calls_made,
                trace.time_ms,
                json.dumps(trace.context_retrieved),
                trace.timestamp.isoformat(),
            ),
        )
        await self.db.commit()

    async def get_traces(self, filters: TraceFilters) -> list[EnrichmentTrace]:
        query = "SELECT * FROM enrichment_trace WHERE 1=1"
        params = []
        if filters.item_id:
            query += " AND item_id = ?"
            params.append(filters.item_id)
        if filters.since:
            query += " AND timestamp >= ?"
            params.append(filters.since.isoformat())
        query += " ORDER BY timestamp DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_trace(r) for r in rows]

    def _row_to_trace(self, row) -> EnrichmentTrace:
        return EnrichmentTrace(
            id=row["id"],
            item_id=row["item_id"],
            depth=row["depth"],
            calls_made=row["calls_made"],
            time_ms=row["time_ms"],
            context_retrieved=json.loads(row["context_retrieved"]),
            timestamp=row["timestamp"],
        )
