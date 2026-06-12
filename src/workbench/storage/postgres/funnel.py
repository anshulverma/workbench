from __future__ import annotations

import json

import asyncpg

from workbench.storage.base import FunnelTracesStore, FunnelOrderStore


class PgFunnelTracesStore(FunnelTracesStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_stages(self, item_id: str) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT stage_data FROM funnel_stages WHERE item_id = $1 "
            "ORDER BY created_at",
            item_id,
        )
        result = []
        for r in rows:
            data = r["stage_data"]
            if isinstance(data, str):
                data = json.loads(data)
            result.append(data)
        return result

    async def log_stage(self, item_id: str, stage: dict) -> None:
        await self.pool.execute(
            """INSERT INTO funnel_stages (item_id, stage_data)
               VALUES ($1, $2::jsonb)""",
            item_id,
            json.dumps(stage),
        )

    async def delete_older_than(self, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM funnel_stages "
            "WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(result.split()[-1])


class PgFunnelOrderStore(FunnelOrderStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_order(self) -> list[dict]:
        rows = await self.pool.fetch("SELECT * FROM funnel_order ORDER BY position")
        return [
            {
                "stage_id": r["stage_id"],
                "label": r["label"],
                "enabled": r["enabled"],
                "position": r["position"],
            }
            for r in rows
        ]

    async def set_order(self, entries: list[dict]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM funnel_order")
                for i, entry in enumerate(entries):
                    await conn.execute(
                        """INSERT INTO funnel_order
                           (stage_id, label, enabled, position)
                           VALUES ($1, $2, $3, $4)""",
                        entry["stage_id"],
                        entry.get("label", ""),
                        entry.get("enabled", True),
                        i,
                    )

    async def toggle_stage(self, stage_id: str, enabled: bool) -> None:
        await self.pool.execute(
            "UPDATE funnel_order SET enabled = $1 WHERE stage_id = $2",
            enabled,
            stage_id,
        )
