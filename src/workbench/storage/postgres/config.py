from __future__ import annotations

import asyncpg

from workbench.storage.base import ConfigStore


class PgConfigStore(ConfigStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get(self, key: str) -> str | None:
        row = await self.pool.fetchrow(
            "SELECT value FROM config WHERE key = $1", key
        )
        return row["value"] if row else None

    async def set(self, key: str, value: str) -> None:
        await self.pool.execute(
            "INSERT INTO config (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            key,
            value,
        )

    async def get_all(self) -> dict[str, str]:
        rows = await self.pool.fetch("SELECT key, value FROM config")
        return {row["key"]: row["value"] for row in rows}
