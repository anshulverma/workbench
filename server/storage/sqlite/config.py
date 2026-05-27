from server.storage.base import ConfigStore


class SqliteConfigStore(ConfigStore):
    def __init__(self, db):
        self.db = db

    async def get(self, key: str) -> str | None:
        cursor = await self.db.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    async def get_all(self) -> dict[str, str]:
        cursor = await self.db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
