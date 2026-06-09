from __future__ import annotations

import json

import asyncpg

from workbench.domain import (
    SourceConfig,
    SourceConfigUpdate,
    SourceRelevanceConfig,
)
from workbench.storage.base import SourceConfigStore


class PgSourceConfigStore(SourceConfigStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_sources(self) -> list[SourceConfig]:
        rows = await self.pool.fetch(
            "SELECT * FROM source_configs ORDER BY created_at DESC"
        )
        return [self._row_to_source(r) for r in rows]

    async def get_source(self, source_id: str) -> SourceConfig | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM source_configs WHERE id = $1", source_id
        )
        return self._row_to_source(row) if row else None

    async def upsert_source(self, source: SourceConfig) -> SourceConfig:
        await self.pool.execute(
            """INSERT INTO source_configs
               (id, adapter_type, config, schedule, enabled, relevance, created_at)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7)
               ON CONFLICT (id) DO UPDATE SET
                 adapter_type = EXCLUDED.adapter_type,
                 config = EXCLUDED.config,
                 schedule = EXCLUDED.schedule,
                 enabled = EXCLUDED.enabled,
                 relevance = EXCLUDED.relevance""",
            source.id,
            source.adapter_type,
            json.dumps(source.config),
            source.schedule,
            source.enabled,
            json.dumps(source.relevance.model_dump()) if source.relevance else None,
            source.created_at,
        )
        return source

    async def update_source(
        self, source_id: str, updates: SourceConfigUpdate
    ) -> SourceConfig:
        sets: list[str] = []
        params: list = []
        idx = 1
        if updates.config is not None:
            sets.append(f"config = ${idx}::jsonb")
            params.append(json.dumps(updates.config))
            idx += 1
        if updates.schedule is not None:
            sets.append(f"schedule = ${idx}")
            params.append(updates.schedule)
            idx += 1
        if updates.enabled is not None:
            sets.append(f"enabled = ${idx}")
            params.append(updates.enabled)
            idx += 1
        if updates.relevance is not None:
            sets.append(f"relevance = ${idx}::jsonb")
            params.append(json.dumps(updates.relevance.model_dump()))
            idx += 1
        if not sets:
            return await self.get_source(source_id)  # type: ignore[return-value]
        params.append(source_id)
        await self.pool.execute(
            f"UPDATE source_configs SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )
        return await self.get_source(source_id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_source(row: asyncpg.Record) -> SourceConfig:
        cfg = row["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        rel = row["relevance"] if "relevance" in row else None
        if isinstance(rel, str):
            rel = json.loads(rel)
        return SourceConfig(
            id=row["id"],
            adapter_type=row["adapter_type"],
            config=cfg,
            schedule=row["schedule"],
            enabled=row["enabled"],
            relevance=SourceRelevanceConfig(**rel) if rel else None,
            created_at=row["created_at"],
        )
