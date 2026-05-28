from workbench.storage.base import FilterRuleStore
from workbench.models import FilterRule


class SqliteFilterRuleStore(FilterRuleStore):
    def __init__(self, db):
        self.db = db

    async def get_rules(self) -> list[FilterRule]:
        cursor = await self.db.execute("SELECT * FROM filter_rules ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_rule(r) for r in rows]

    async def add_rule(self, rule: FilterRule) -> FilterRule:
        await self.db.execute(
            "INSERT INTO filter_rules (id, source_type, pattern, action, priority, created_from_interaction_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                rule.id,
                rule.source_type,
                rule.pattern,
                rule.action,
                rule.priority.value if rule.priority else None,
                rule.created_from_interaction_id,
            ),
        )
        await self.db.commit()
        return rule

    async def get_source_rules(self, source_type: str) -> list[FilterRule]:
        cursor = await self.db.execute(
            "SELECT * FROM filter_rules WHERE source_type = ? ORDER BY created_at DESC",
            (source_type,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_rule(r) for r in rows]

    def _row_to_rule(self, row) -> FilterRule:
        return FilterRule(
            id=row["id"],
            source_type=row["source_type"],
            pattern=row["pattern"],
            action=row["action"],
            priority=row["priority"],
            created_from_interaction_id=row["created_from_interaction_id"],
        )
