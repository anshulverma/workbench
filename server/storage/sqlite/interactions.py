import json
from server.storage.base import InteractionStore
from server.models import InteractionEntry


class SqliteInteractionStore(InteractionStore):
    def __init__(self, db):
        self.db = db

    async def append(self, entry: InteractionEntry) -> None:
        await self.db.execute(
            "INSERT INTO interaction_log (id, timestamp, source_type, item_id, item_summary, triage_card_full, enrichment_context, options_presented, option_chosen, todo_created, enrichment_depth, enrichment_calls, enrichment_time_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.timestamp.isoformat(),
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
            ),
        )
        await self.db.commit()

    async def get_since(self, cursor: int, limit: int) -> list[InteractionEntry]:
        sql = "SELECT * FROM interaction_log ORDER BY timestamp ASC LIMIT ? OFFSET ?"
        cur = await self.db.execute(sql, (limit, cursor))
        rows = await cur.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def count(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) FROM interaction_log")
        row = await cur.fetchone()
        return row[0]

    async def get_all(self) -> list[InteractionEntry]:
        cur = await self.db.execute("SELECT * FROM interaction_log ORDER BY timestamp ASC")
        rows = await cur.fetchall()
        return [self._row_to_entry(r) for r in rows]

    def _row_to_entry(self, row) -> InteractionEntry:
        todo = row["todo_created"]
        return InteractionEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            source_type=row["source_type"],
            item_id=row["item_id"],
            item_summary=row["item_summary"],
            triage_card_full=json.loads(row["triage_card_full"]),
            enrichment_context=json.loads(row["enrichment_context"]),
            options_presented=json.loads(row["options_presented"]),
            option_chosen=row["option_chosen"],
            todo_created=json.loads(todo) if todo else None,
            enrichment_depth=row["enrichment_depth"],
            enrichment_calls=row["enrichment_calls"],
            enrichment_time_ms=row["enrichment_time_ms"],
        )
