from __future__ import annotations

import json

import asyncpg

from workbench.domain import LoopBackConfig
from workbench.storage.base import LoopBacksStore


class PgLoopBacksStore(LoopBacksStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_loopbacks(self) -> list[LoopBackConfig]:
        rows = await self.pool.fetch("SELECT * FROM loopbacks ORDER BY created_at")
        return [self._row_to_loopback(r) for r in rows]

    async def get_loopback(self, loopback_id: str) -> LoopBackConfig | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM loopbacks WHERE id = $1", loopback_id
        )
        return self._row_to_loopback(row) if row else None

    async def upsert_loopback(self, loopback: LoopBackConfig) -> LoopBackConfig:
        # id is a BIGINT identity column. A new loopback (id is None) is
        # INSERTed without it so the DB assigns one (written back onto the
        # config); an existing loopback upserts by id.
        values = [
            loopback.name,
            loopback.trigger,
            loopback.target_stage,
            loopback.max_iterations,
            loopback.enabled,
            json.dumps(loopback.config),
            loopback.created_at,
        ]
        if loopback.id is None:
            row = await self.pool.fetchrow(
                """INSERT INTO loopbacks
                   (name, trigger, target_stage, max_iterations,
                    enabled, config, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                   RETURNING id""",
                *values,
            )
            loopback.id = row["id"]
        else:
            await self.pool.execute(
                """INSERT INTO loopbacks
                   (id, name, trigger, target_stage, max_iterations,
                    enabled, config, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                   ON CONFLICT (id) DO UPDATE SET
                     name = EXCLUDED.name,
                     trigger = EXCLUDED.trigger,
                     target_stage = EXCLUDED.target_stage,
                     max_iterations = EXCLUDED.max_iterations,
                     enabled = EXCLUDED.enabled,
                     config = EXCLUDED.config""",
                loopback.id,
                *values,
            )
        return loopback

    async def delete_loopback(self, loopback_id: str) -> None:
        await self.pool.execute("DELETE FROM loopbacks WHERE id = $1", loopback_id)

    @staticmethod
    def _row_to_loopback(row: asyncpg.Record) -> LoopBackConfig:
        cfg = row["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return LoopBackConfig(
            id=row["id"],
            name=row["name"],
            trigger=row["trigger"],
            target_stage=row["target_stage"],
            max_iterations=row["max_iterations"],
            enabled=row["enabled"],
            config=cfg,
            created_at=row["created_at"],
        )
