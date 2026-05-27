import json
from server.storage.base import SourceConfigStore
from server.models import SourceConfig, SourceConfigUpdate


class SqliteSourceConfigStore(SourceConfigStore):
    def __init__(self, db):
        self.db = db

    async def get_sources(self) -> list[SourceConfig]:
        cursor = await self.db.execute("SELECT * FROM source_configs ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_source(r) for r in rows]

    async def save_source(self, source: SourceConfig) -> SourceConfig:
        await self.db.execute(
            "INSERT INTO source_configs (id, adapter_type, config, schedule, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.adapter_type,
                json.dumps(source.config),
                source.schedule,
                1 if source.enabled else 0,
                source.created_at.isoformat(),
            ),
        )
        await self.db.commit()
        return source

    async def update_source(self, source_id: str, updates: SourceConfigUpdate) -> SourceConfig:
        sets, params = [], []
        if updates.config is not None:
            sets.append("config = ?")
            params.append(json.dumps(updates.config))
        if updates.schedule is not None:
            sets.append("schedule = ?")
            params.append(updates.schedule)
        if updates.enabled is not None:
            sets.append("enabled = ?")
            params.append(1 if updates.enabled else 0)
        if not sets:
            return await self._get_source(source_id)
        params.append(source_id)
        await self.db.execute(f"UPDATE source_configs SET {', '.join(sets)} WHERE id = ?", params)
        await self.db.commit()
        return await self._get_source(source_id)

    async def delete_source(self, source_id: str) -> None:
        await self.db.execute("DELETE FROM source_configs WHERE id = ?", (source_id,))
        await self.db.commit()

    async def _get_source(self, source_id: str) -> SourceConfig:
        cursor = await self.db.execute("SELECT * FROM source_configs WHERE id = ?", (source_id,))
        row = await cursor.fetchone()
        return self._row_to_source(row)

    def _row_to_source(self, row) -> SourceConfig:
        return SourceConfig(
            id=row["id"],
            adapter_type=row["adapter_type"],
            config=json.loads(row["config"]),
            schedule=row["schedule"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )
