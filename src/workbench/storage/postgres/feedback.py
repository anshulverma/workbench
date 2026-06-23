from __future__ import annotations

import json

import asyncpg

from workbench.domain import FeedbackCorrection, FilterTuningTask
from workbench.storage.base import FeedbackStore


class PgFeedbackStore(FeedbackStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_corrections(
        self, item_id: int | None = None
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
               (item_id, rule_id, filter_id, item_summary, original_action,
                corrected_action, from_label, to_label, reason, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
            correction.item_id,
            correction.rule_id,
            correction.filter_id,
            correction.item_summary,
            correction.original_action,
            correction.corrected_action,
            correction.from_label,
            correction.to_label,
            correction.reason,
            correction.created_at,
        )
        correction.id = row["id"]
        return correction

    async def delete_correction(self, correction_id: int) -> None:
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
               (rule_id, filter_id, item_id, item_summary, from_outcome,
                to_outcome, from_label, to_label, filter_prompt, proposed_prompt,
                kind, correction_ids, status, created_at, resolved_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15)
               RETURNING id""",
            task.rule_id,
            task.filter_id,
            task.item_id,
            task.item_summary,
            task.from_outcome,
            task.to_outcome,
            task.from_label,
            task.to_label,
            task.filter_prompt,
            task.proposed_prompt,
            task.kind,
            json.dumps(task.correction_ids),
            task.status,
            task.created_at,
            task.resolved_at,
        )
        task.id = row["id"]
        return task

    async def update_task(self, task_id: int, status: str) -> FilterTuningTask:
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

    async def delete_task(self, task_id: int) -> None:
        await self.pool.execute(
            "DELETE FROM filter_tuning_tasks WHERE id = $1", task_id
        )

    @staticmethod
    def _row_to_correction(row: asyncpg.Record) -> FeedbackCorrection:
        return FeedbackCorrection(
            id=row["id"],
            item_id=row["item_id"],
            rule_id=row["rule_id"],
            filter_id=row["filter_id"],
            item_summary=row["item_summary"],
            original_action=row["original_action"],
            corrected_action=row["corrected_action"],
            from_label=row["from_label"],
            to_label=row["to_label"],
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
            filter_id=row["filter_id"],
            item_id=row["item_id"],
            item_summary=row["item_summary"],
            from_outcome=row["from_outcome"],
            to_outcome=row["to_outcome"],
            from_label=row["from_label"],
            to_label=row["to_label"],
            filter_prompt=row["filter_prompt"],
            proposed_prompt=row["proposed_prompt"],
            kind=row["kind"],
            correction_ids=cids,
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )
