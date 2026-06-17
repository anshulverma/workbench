from __future__ import annotations

import json

import asyncpg

from workbench.domain import FeedbackCorrection, FilterTuningTask
from workbench.storage.base import FeedbackStore


class PgFeedbackStore(FeedbackStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_corrections(
        self, item_id: str | None = None
    ) -> list[FeedbackCorrection]:
        if item_id:
            rows = await self.pool.fetch(
                "SELECT * FROM feedback_corrections WHERE item_id = $1 "
                "ORDER BY created_at DESC",
                item_id,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM feedback_corrections ORDER BY created_at DESC"
            )
        return [self._row_to_correction(r) for r in rows]

    async def add_correction(
        self, correction: FeedbackCorrection
    ) -> FeedbackCorrection:
        # id is a BIGINT identity column — omit it on INSERT, let the DB assign
        # one, then write it back onto the passed correction.
        row = await self.pool.fetchrow(
            """INSERT INTO feedback_corrections
               (item_id, rule_id, original_action, corrected_action,
                reason, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id""",
            correction.item_id,
            correction.rule_id,
            correction.original_action,
            correction.corrected_action,
            correction.reason,
            correction.created_at,
        )
        correction.id = row["id"]
        return correction

    async def delete_correction(self, correction_id: str) -> None:
        await self.pool.execute(
            "DELETE FROM feedback_corrections WHERE id = $1", correction_id
        )

    async def get_tasks(self, status: str | None = None) -> list[FilterTuningTask]:
        if status:
            rows = await self.pool.fetch(
                "SELECT * FROM filter_tuning_tasks WHERE status = $1 "
                "ORDER BY created_at DESC",
                status,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM filter_tuning_tasks ORDER BY created_at DESC"
            )
        return [self._row_to_task(r) for r in rows]

    async def add_task(self, task: FilterTuningTask) -> FilterTuningTask:
        # id is a BIGINT identity column — omit it on INSERT, let the DB assign
        # one, then write it back onto the passed task.
        row = await self.pool.fetchrow(
            """INSERT INTO filter_tuning_tasks
               (rule_id, proposed_prompt, correction_ids, status,
                created_at, resolved_at)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6)
               RETURNING id""",
            task.rule_id,
            task.proposed_prompt,
            json.dumps(task.correction_ids),
            task.status,
            task.created_at,
            task.resolved_at,
        )
        task.id = row["id"]
        return task

    async def update_task(self, task_id: str, status: str) -> FilterTuningTask:
        await self.pool.execute(
            "UPDATE filter_tuning_tasks SET status = $1, "
            "resolved_at = CASE WHEN $1 IN ('applied', 'dismissed') "
            "THEN NOW() ELSE resolved_at END "
            "WHERE id = $2",
            status,
            task_id,
        )
        row = await self.pool.fetchrow(
            "SELECT * FROM filter_tuning_tasks WHERE id = $1", task_id
        )
        return self._row_to_task(row)

    async def delete_task(self, task_id: str) -> None:
        await self.pool.execute(
            "DELETE FROM filter_tuning_tasks WHERE id = $1", task_id
        )

    @staticmethod
    def _row_to_correction(row: asyncpg.Record) -> FeedbackCorrection:
        return FeedbackCorrection(
            id=row["id"],
            item_id=row["item_id"],
            rule_id=row["rule_id"],
            original_action=row["original_action"],
            corrected_action=row["corrected_action"],
            reason=row["reason"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_task(row: asyncpg.Record) -> FilterTuningTask:
        cids = row["correction_ids"]
        if isinstance(cids, str):
            cids = json.loads(cids)
        return FilterTuningTask(
            id=row["id"],
            rule_id=row["rule_id"],
            proposed_prompt=row["proposed_prompt"],
            correction_ids=cids,
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )
