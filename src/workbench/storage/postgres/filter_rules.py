from __future__ import annotations

import asyncpg

from workbench.models import FilterRule
from workbench.storage.base import FilterRuleStore


class PgFilterRuleStore(FilterRuleStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_rules(self) -> list[FilterRule]:
        rows = await self.pool.fetch(
            "SELECT * FROM filter_rules ORDER BY created_at DESC"
        )
        return [self._row_to_rule(r) for r in rows]

    async def add_rule(self, rule: FilterRule) -> FilterRule:
        await self.pool.execute(
            """INSERT INTO filter_rules
               (id, source_type, pattern, action, priority,
                created_from_interaction_id)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            rule.id,
            rule.source_type,
            rule.pattern,
            rule.action,
            rule.priority.value if rule.priority else None,
            rule.created_from_interaction_id,
        )
        return rule

    async def get_source_rules(self, source_type: str) -> list[FilterRule]:
        rows = await self.pool.fetch(
            "SELECT * FROM filter_rules WHERE source_type = $1 "
            "ORDER BY created_at DESC",
            source_type,
        )
        return [self._row_to_rule(r) for r in rows]

    @staticmethod
    def _row_to_rule(row: asyncpg.Record) -> FilterRule:
        return FilterRule(
            id=row["id"],
            source_type=row["source_type"],
            pattern=row["pattern"],
            action=row["action"],
            priority=row["priority"],
            created_from_interaction_id=row["created_from_interaction_id"],
        )
