from __future__ import annotations

import json

import asyncpg

from workbench.models import InteractionEntry
from workbench.storage.base import InteractionStore


class PgInteractionStore(InteractionStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def append(self, entry: InteractionEntry) -> None:
        await self.pool.execute(
            """INSERT INTO interaction_log
               (id, timestamp, source_type, item_id, item_summary,
                triage_card_full, enrichment_context, options_presented,
                option_chosen, todo_created, enrichment_depth,
                enrichment_calls, enrichment_time_ms)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
                       $9, $10::jsonb, $11, $12, $13)""",
            entry.id,
            entry.timestamp,
            entry.source_type,
            entry.item_id,
            entry.item_summary,
            json.dumps(entry.triage_card_full),
            json.dumps(entry.enrichment_context),
            json.dumps(entry.options_presented),
            entry.option_chosen,
            json.dumps(entry.todo_created) if entry.todo_created else None,
            entry.enrichment_depth,
            entry.enrichment_calls,
            entry.enrichment_time_ms,
        )

    async def get_since(self, cursor: int, limit: int) -> list[InteractionEntry]:
        rows = await self.pool.fetch(
            "SELECT * FROM interaction_log ORDER BY timestamp ASC LIMIT $1 OFFSET $2",
            limit,
            cursor,
        )
        return [self._row_to_entry(r) for r in rows]

    async def count(self) -> int:
        row = await self.pool.fetchrow("SELECT COUNT(*) AS cnt FROM interaction_log")
        return row["cnt"]  # type: ignore[index]

    async def get_all(self) -> list[InteractionEntry]:
        rows = await self.pool.fetch(
            "SELECT * FROM interaction_log ORDER BY timestamp ASC"
        )
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row: asyncpg.Record) -> InteractionEntry:
        triage_card_full = row["triage_card_full"]
        if isinstance(triage_card_full, str):
            triage_card_full = json.loads(triage_card_full)

        enrichment_context = row["enrichment_context"]
        if isinstance(enrichment_context, str):
            enrichment_context = json.loads(enrichment_context)

        options_presented = row["options_presented"]
        if isinstance(options_presented, str):
            options_presented = json.loads(options_presented)

        todo = row["todo_created"]
        if isinstance(todo, str):
            todo = json.loads(todo)

        return InteractionEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            source_type=row["source_type"],
            item_id=row["item_id"],
            item_summary=row["item_summary"],
            triage_card_full=triage_card_full,
            enrichment_context=enrichment_context,
            options_presented=options_presented,
            option_chosen=row["option_chosen"],
            todo_created=todo,
            enrichment_depth=row["enrichment_depth"],
            enrichment_calls=row["enrichment_calls"],
            enrichment_time_ms=row["enrichment_time_ms"],
        )
