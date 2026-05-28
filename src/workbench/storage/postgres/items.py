from __future__ import annotations

import json

import asyncpg

from workbench.models import Item, ItemFilters, ItemStatus, ItemUpdate
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
        await self.pool.execute(
            """INSERT INTO items
               (id, source_type, source_id, summary, category, origin,
                priority, status, raw_data, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)""",
            item.id,
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
        )
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

    @staticmethod
    def _row_to_item(row: asyncpg.Record) -> Item:
        raw = row["raw_data"]
        if isinstance(raw, str):
            raw = json.loads(raw)
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
        )
