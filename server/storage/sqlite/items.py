import json
from server.storage.base import ItemStore
from server.models import Item, ItemFilters, ItemUpdate, ItemStatus


class SqliteItemStore(ItemStore):
    def __init__(self, db):
        self.db = db

    async def get_items(self, filters: ItemFilters) -> list[Item]:
        query = "SELECT * FROM items WHERE 1=1"
        params = []
        if filters.status:
            query += " AND status = ?"
            params.append(filters.status.value)
        if filters.priority:
            query += " AND priority = ?"
            params.append(filters.priority.value)
        if filters.source_type:
            query += " AND source_type = ?"
            params.append(filters.source_type)
        if filters.category:
            query += " AND category = ?"
            params.append(filters.category.value)
        query += " ORDER BY created_at DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        cursor = await self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return self._row_to_item(row) if row else None

    async def save_item(self, item: Item) -> Item:
        await self.db.execute(
            "INSERT INTO items (id, source_type, source_id, summary, category, origin, priority, status, raw_data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.source_type, item.source_id, item.summary, item.category.value, item.origin.value, item.priority.value, item.status.value, json.dumps(item.raw_data), item.created_at.isoformat(), item.updated_at.isoformat()),
        )
        await self.db.commit()
        return item

    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item:
        sets, params = [], []
        if updates.priority is not None:
            sets.append("priority = ?")
            params.append(updates.priority.value)
        if updates.status is not None:
            sets.append("status = ?")
            params.append(updates.status.value)
        if updates.summary is not None:
            sets.append("summary = ?")
            params.append(updates.summary)
        sets.append("updated_at = datetime('now')")
        params.append(item_id)
        await self.db.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params)
        await self.db.commit()
        return await self.get_item(item_id)

    async def archive_item(self, item_id: str) -> None:
        await self.db.execute("UPDATE items SET status = 'archived', updated_at = datetime('now') WHERE id = ?", (item_id,))
        await self.db.commit()

    def _row_to_item(self, row) -> Item:
        return Item(
            id=row["id"], source_type=row["source_type"], source_id=row["source_id"],
            summary=row["summary"], category=row["category"], origin=row["origin"],
            priority=row["priority"], status=row["status"],
            raw_data=json.loads(row["raw_data"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
