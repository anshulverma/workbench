from __future__ import annotations

import json

import asyncpg

from workbench.domain import FilterRule
from workbench.storage.base import FilterRuleStore


class PgFilterRuleStore(FilterRuleStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_rules(self) -> list[FilterRule]:
        rows = await self.pool.fetch(
            "SELECT * FROM filter_rules ORDER BY order_index, created_at DESC"
        )
        return [self._row_to_rule(r) for r in rows]

    async def add_rule(self, rule: FilterRule) -> FilterRule:
        await self.pool.execute(
            """INSERT INTO filter_rules
               (id, source_type, pattern, prompt, action, priority,
                created_from_interaction_id, sources, confidence,
                origin, matched, enabled, label, order_index)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                       $9, $10, $11, $12, $13, $14)""",
            rule.id,
            rule.source_type,
            rule.pattern,
            rule.prompt,
            rule.action,
            rule.priority.value if rule.priority else None,
            rule.created_from_interaction_id,
            json.dumps(rule.sources),
            rule.confidence,
            rule.origin,
            rule.matched,
            rule.enabled,
            rule.label,
            rule.order_index,
        )
        return rule

    async def get_source_rules(self, source_type: str) -> list[FilterRule]:
        rows = await self.pool.fetch(
            "SELECT * FROM filter_rules WHERE source_type = $1 "
            "ORDER BY order_index, created_at DESC",
            source_type,
        )
        return [self._row_to_rule(r) for r in rows]

    async def update_rule(self, rule_id: str, updates: dict) -> FilterRule:
        sets: list[str] = []
        params: list = []
        idx = 1
        for key, value in updates.items():
            if key == "sources":
                sets.append(f"sources = ${idx}::jsonb")
                params.append(json.dumps(value))
            elif key == "priority":
                sets.append(f"priority = ${idx}")
                params.append(value.value if hasattr(value, "value") else value)
            else:
                sets.append(f"{key} = ${idx}")
                params.append(value)
            idx += 1
        if not sets:
            row = await self.pool.fetchrow(
                "SELECT * FROM filter_rules WHERE id = $1", rule_id
            )
            return self._row_to_rule(row)
        params.append(rule_id)
        await self.pool.execute(
            f"UPDATE filter_rules SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )
        row = await self.pool.fetchrow(
            "SELECT * FROM filter_rules WHERE id = $1", rule_id
        )
        return self._row_to_rule(row)

    async def delete_rule(self, rule_id: str) -> None:
        await self.pool.execute("DELETE FROM filter_rules WHERE id = $1", rule_id)

    async def reorder_rules(self, rule_ids: list[str]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for idx, rule_id in enumerate(rule_ids):
                    await conn.execute(
                        "UPDATE filter_rules SET order_index = $1 WHERE id = $2",
                        idx,
                        rule_id,
                    )

    @staticmethod
    def _row_to_rule(row: asyncpg.Record) -> FilterRule:
        sources = row.get("sources")
        if isinstance(sources, str):
            sources = json.loads(sources)
        return FilterRule(
            id=row["id"],
            source_type=row["source_type"],
            pattern=row.get("pattern"),
            prompt=row.get("prompt"),
            action=row["action"],
            priority=row["priority"],
            created_from_interaction_id=row["created_from_interaction_id"],
            sources=sources if sources else [],
            confidence=row.get("confidence", 50),
            origin=row.get("origin", "manual"),
            matched=row.get("matched", 0),
            enabled=row.get("enabled", True),
            label=row.get("label"),
            order_index=row.get("order_index", 0),
        )
