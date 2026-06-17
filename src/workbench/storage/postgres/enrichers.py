from __future__ import annotations

import json

import asyncpg

from workbench.domain import EnricherConfig
from workbench.storage.base import EnrichersStore


class PgEnrichersStore(EnrichersStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_enrichers(self) -> list[EnricherConfig]:
        rows = await self.pool.fetch(
            "SELECT * FROM enrichers ORDER BY order_index, created_at"
        )
        return [self._row_to_enricher(r) for r in rows]

    async def get_enricher(self, enricher_id: str) -> EnricherConfig | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM enrichers WHERE id = $1", enricher_id
        )
        return self._row_to_enricher(row) if row else None

    async def upsert_enricher(self, enricher: EnricherConfig) -> EnricherConfig:
        # id is a BIGINT identity column. A new enricher (id is None) is
        # INSERTed without it so the DB assigns one (written back onto the
        # config); an existing enricher upserts by id.
        values = [
            enricher.name,
            enricher.stage,
            enricher.provider,
            enricher.enabled,
            json.dumps(enricher.config),
            enricher.order_index,
            enricher.created_at,
        ]
        if enricher.id is None:
            row = await self.pool.fetchrow(
                """INSERT INTO enrichers
                   (name, stage, provider, enabled, config, order_index, created_at)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                   RETURNING id""",
                *values,
            )
            enricher.id = row["id"]
        else:
            await self.pool.execute(
                """INSERT INTO enrichers
                   (id, name, stage, provider, enabled, config, order_index, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                   ON CONFLICT (id) DO UPDATE SET
                     name = EXCLUDED.name,
                     stage = EXCLUDED.stage,
                     provider = EXCLUDED.provider,
                     enabled = EXCLUDED.enabled,
                     config = EXCLUDED.config,
                     order_index = EXCLUDED.order_index""",
                enricher.id,
                *values,
            )
        return enricher

    async def delete_enricher(self, enricher_id: str) -> None:
        await self.pool.execute("DELETE FROM enrichers WHERE id = $1", enricher_id)

    @staticmethod
    def _row_to_enricher(row: asyncpg.Record) -> EnricherConfig:
        cfg = row["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return EnricherConfig(
            id=row["id"],
            name=row["name"],
            stage=row["stage"],
            provider=row["provider"],
            enabled=row["enabled"],
            config=cfg,
            order_index=row["order_index"],
            created_at=row["created_at"],
        )
