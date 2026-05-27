import json
from server.storage.base import PlanStore
from server.models import Plan, PlanFilters, PlanUpdate


class SqlitePlanStore(PlanStore):
    def __init__(self, db):
        self.db = db

    async def get_plans(self, filters: PlanFilters) -> list[Plan]:
        query = "SELECT * FROM plans WHERE 1=1"
        params = []
        if filters.status:
            query += " AND status = ?"
            params.append(filters.status)
        query += " ORDER BY created_at DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_plan(r) for r in rows]

    async def save_plan(self, plan: Plan) -> Plan:
        await self.db.execute(
            "INSERT INTO plans (id, title, status, content, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                plan.id,
                plan.title,
                plan.status,
                plan.content,
                json.dumps(plan.sources),
                plan.created_at.isoformat(),
            ),
        )
        await self.db.commit()
        return plan

    async def update_plan(self, plan_id: str, updates: PlanUpdate) -> Plan:
        sets, params = [], []
        if updates.title is not None:
            sets.append("title = ?")
            params.append(updates.title)
        if updates.status is not None:
            sets.append("status = ?")
            params.append(updates.status)
        if updates.content is not None:
            sets.append("content = ?")
            params.append(updates.content)
        if not sets:
            return await self._get_plan(plan_id)
        params.append(plan_id)
        await self.db.execute(f"UPDATE plans SET {', '.join(sets)} WHERE id = ?", params)
        await self.db.commit()
        return await self._get_plan(plan_id)

    async def _get_plan(self, plan_id: str) -> Plan:
        cursor = await self.db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        row = await cursor.fetchone()
        return self._row_to_plan(row)

    def _row_to_plan(self, row) -> Plan:
        return Plan(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            content=row["content"],
            sources=json.loads(row["sources"]),
            created_at=row["created_at"],
        )
