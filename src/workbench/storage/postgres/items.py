from __future__ import annotations

import json

import asyncpg

from workbench.domain import Item, ItemFilters, ItemStatus, ItemUpdate, RawItem
from workbench.storage.base import ItemStore


class PgItemStore(ItemStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_items(self, filters: ItemFilters) -> list[Item]:
        query = "SELECT * FROM items WHERE 1=1"
        params: list = []
        idx = 1
        if filters.status:
            query += f" AND status = ${idx}"
            params.append(filters.status.value)
            idx += 1
        if filters.priority:
            query += f" AND priority = ${idx}"
            params.append(filters.priority.value)
            idx += 1
        if filters.source_type:
            query += f" AND source_type = ${idx}"
            params.append(filters.source_type)
            idx += 1
        if filters.category:
            query += f" AND category = ${idx}"
            params.append(filters.category.value)
            idx += 1
        query += " ORDER BY created_at DESC"
        rows = await self.pool.fetch(query, *params)
        return [self._row_to_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        row = await self.pool.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
        return self._row_to_item(row) if row else None

    async def save_item(self, item: Item) -> Item:
        # id is a BIGINT identity column — omit it on INSERT and let the DB
        # assign one, then write it back onto the passed Item so callers that
        # link to it (e.g. card.item_id = item.id) see the real value.
        row = await self.pool.fetchrow(
            """INSERT INTO items
               (source_type, source_id, summary, category, origin,
                priority, status, raw_data, created_at, updated_at,
                parent_item_id, action_source, action_category,
                snoozed_until, completed_at,
                tags, llm_summary, enriched_context, funnel_log,
                verdict_action, verdict_priority, verdict_confidence)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9,
                       $10, $11, $12, $13, $14, $15,
                       $16::jsonb, $17, $18::jsonb, $19::jsonb,
                       $20, $21, $22)
               RETURNING id""",
            item.source_type,
            item.source_id,
            item.summary,
            item.category.value,
            item.origin.value,
            item.priority.value,
            item.status.value,
            json.dumps(item.raw_data),
            item.created_at,
            item.updated_at,
            item.parent_item_id,
            item.action_source,
            item.action_category,
            item.snoozed_until,
            item.completed_at,
            json.dumps(item.tags),
            item.llm_summary,
            json.dumps(item.enriched_context),
            json.dumps(item.funnel_log),
            item.verdict_action,
            item.verdict_priority,
            item.verdict_confidence,
        )
        item.id = row["id"]
        return item

    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item:
        sets: list[str] = []
        params: list = []
        idx = 1
        if updates.priority is not None:
            sets.append(f"priority = ${idx}")
            params.append(updates.priority.value)
            idx += 1
        if updates.status is not None:
            sets.append(f"status = ${idx}")
            params.append(updates.status.value)
            idx += 1
        if updates.summary is not None:
            sets.append(f"summary = ${idx}")
            params.append(updates.summary)
            idx += 1
        sets.append("updated_at = NOW()")
        params.append(item_id)
        await self.pool.execute(
            f"UPDATE items SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )
        return await self.get_item(item_id)  # type: ignore[return-value]

    async def archive_item(self, item_id: str) -> None:
        await self.pool.execute(
            "UPDATE items SET status = 'archived', updated_at = NOW() WHERE id = $1",
            item_id,
        )

    async def get_items_by_source(self, source_type: str) -> list[Item]:
        rows = await self.pool.fetch(
            "SELECT * FROM items WHERE source_type = $1 ORDER BY created_at DESC",
            source_type,
        )
        return [self._row_to_item(r) for r in rows]

    async def get_item_by_source_id(
        self, source_type: str, source_id: str
    ) -> Item | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM items WHERE source_type = $1 AND source_id = $2 "
            "AND status NOT IN ('archived', 'done') "
            "ORDER BY created_at DESC LIMIT 1",
            source_type,
            source_id,
        )
        return self._row_to_item(row) if row else None

    async def get_active_by_source(self, source_type: str) -> list[Item]:
        rows = await self.pool.fetch(
            "SELECT * FROM items WHERE source_type = $1 "
            "AND status NOT IN ('archived', 'done') "
            "ORDER BY created_at DESC",
            source_type,
        )
        return [self._row_to_item(r) for r in rows]

    async def update_raw_data(self, item_id: str, raw_item: RawItem) -> None:
        await self.pool.execute(
            "UPDATE items SET raw_data = $2::jsonb, updated_at = NOW() WHERE id = $1",
            item_id,
            json.dumps(raw_item.model_dump()),
        )

    async def delete_older_than(self, status: str, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM items WHERE status = $1 AND updated_at < NOW() - INTERVAL '1 day' * $2",
            status,
            days,
        )
        return int(result.split()[-1])

    async def _count_group(self, column: str) -> dict[str, int]:
        rows = await self.pool.fetch(
            f"SELECT {column} AS k, COUNT(*) AS cnt FROM items GROUP BY {column}"
        )
        return {r["k"]: r["cnt"] for r in rows}

    async def count_by_status(self) -> dict[str, int]:
        return await self._count_group("status")

    async def count_by_priority(self) -> dict[str, int]:
        return await self._count_group("priority")

    async def count_by_category(self) -> dict[str, int]:
        return await self._count_group("category")

    async def count_by_source(self) -> dict[str, int]:
        return await self._count_group("source_type")

    async def items_recent(self, limit: int) -> list[Item]:
        rows = await self.pool.fetch(
            "SELECT * FROM items ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return [self._row_to_item(r) for r in rows]

    async def count_created_since(self, hours: int) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM items "
            "WHERE created_at >= NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return int(row["cnt"])

    async def auto_resolved_counts(self, hours: int) -> tuple[int, int]:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) FILTER (WHERE origin = 'auto_included') AS auto, "
            "COUNT(*) AS total FROM items "
            "WHERE created_at >= NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return int(row["auto"]), int(row["total"])

    async def _timeseries(self, column: str, window: int, bucket: str) -> list[tuple]:
        if bucket not in ("hour", "day"):
            bucket = "hour"
        interval = "1 hour" if bucket == "hour" else "1 day"
        rows = await self.pool.fetch(
            f"SELECT date_trunc('{bucket}', {column}, 'UTC') AS ts, COUNT(*) AS cnt "
            f"FROM items WHERE {column} IS NOT NULL "
            f"AND {column} >= NOW() - INTERVAL '{interval}' * $1 "
            "GROUP BY ts ORDER BY ts",
            window,
        )
        return [(r["ts"], int(r["cnt"])) for r in rows]

    async def created_timeseries(self, window: int, bucket: str):
        return await self._timeseries("created_at", window, bucket)

    async def completed_timeseries(self, window: int, bucket: str):
        return await self._timeseries("completed_at", window, bucket)

    @staticmethod
    def _row_to_item(row: asyncpg.Record) -> Item:
        raw = row["raw_data"]
        if isinstance(raw, str):
            raw = json.loads(raw)

        tags = row.get("tags")
        if isinstance(tags, str):
            tags = json.loads(tags)

        enriched_context = row.get("enriched_context")
        if isinstance(enriched_context, str):
            enriched_context = json.loads(enriched_context)

        funnel_log = row.get("funnel_log")
        if isinstance(funnel_log, str):
            funnel_log = json.loads(funnel_log)

        return Item(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            summary=row["summary"],
            category=row["category"],
            origin=row["origin"],
            priority=row["priority"],
            status=row["status"],
            raw_data=raw,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            parent_item_id=row.get("parent_item_id"),
            action_source=row.get("action_source"),
            action_category=row.get("action_category"),
            tags=tags if tags else [],
            llm_summary=row.get("llm_summary"),
            enriched_context=enriched_context if enriched_context else {},
            funnel_log=funnel_log if funnel_log else [],
            verdict_action=row.get("verdict_action"),
            verdict_priority=row.get("verdict_priority"),
            verdict_confidence=row.get("verdict_confidence"),
        )
