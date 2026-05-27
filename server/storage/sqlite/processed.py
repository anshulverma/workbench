from datetime import datetime
from server.storage.base import ProcessedStore


class SqliteProcessedStore(ProcessedStore):
    def __init__(self, db):
        self.db = db

    async def is_processed(self, source_type: str, source_id: str) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM processed WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
        row = await cursor.fetchone()
        return row is not None

    async def mark_processed(self, source_type: str, source_id: str) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO processed (source_type, source_id, processed_at) VALUES (?, ?, ?)",
            (source_type, source_id, datetime.utcnow().isoformat()),
        )
        await self.db.commit()
