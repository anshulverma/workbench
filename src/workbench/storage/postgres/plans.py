from __future__ import annotations

import json

import asyncpg

from workbench.models import Plan, PlanFilters, PlanUpdate
from workbench.storage.base import PlanStore


class PgPlanStore(PlanStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_plans(self, filters: PlanFilters) -> list[Plan]:
        query = "SELECT * FROM plans WHERE 1=1"
        params: list = []
        idx = 1
        if filters.status:
            query += f" AND status = ${idx}"
            params.append(filters.status)
            idx += 1
        query += " ORDER BY created_at DESC"
        rows = await self.pool.fetch(query, *params)
        return [self._row_to_plan(r) for r in rows]

    async def save_plan(self, plan: Plan) -> Plan:
        await self.pool.execute(
            """INSERT INTO plans (id, title, status, content, sources, created_at)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6)""",
            plan.id,
            plan.title,
            plan.status,
            plan.content,
            json.dumps(plan.sources),
            plan.created_at,
        )
        return plan

    async def update_plan(self, plan_id: str, updates: PlanUpdate) -> Plan:
        sets: list[str] = []
        params: list = []
        idx = 1
        if updates.title is not None:
            sets.append(f"title = ${idx}")
            params.append(updates.title)
            idx += 1
        if updates.status is not None:
            sets.append(f"status = ${idx}")
            params.append(updates.status)
            idx += 1
        if updates.content is not None:
            sets.append(f"content = ${idx}")
            params.append(updates.content)
            idx += 1
        if not sets:
            return await self._get_plan(plan_id)
        params.append(plan_id)
        await self.pool.execute(
            f"UPDATE plans SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )
        return await self._get_plan(plan_id)

    async def _get_plan(self, plan_id: str) -> Plan:
        row = await self.pool.fetchrow("SELECT * FROM plans WHERE id = $1", plan_id)
        return self._row_to_plan(row)  # type: ignore[arg-type]

    @staticmethod
    def _row_to_plan(row: asyncpg.Record) -> Plan:
        sources = row["sources"]
        if isinstance(sources, str):
            sources = json.loads(sources)
        return Plan(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            content=row["content"],
            sources=sources,
            created_at=row["created_at"],
        )
