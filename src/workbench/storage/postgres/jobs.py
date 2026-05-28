from __future__ import annotations

import asyncpg

from workbench.models import PipelineJob
from workbench.storage.base import JobStore


class PgJobStore(JobStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def save_job(self, job: PipelineJob) -> PipelineJob:
        await self.pool.execute(
            """INSERT INTO jobs
               (id, trigger, status, input_hash, items_extracted,
                items_included, items_triaged, items_dropped, items_failed,
                error, created_at, completed_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            job.id,
            job.trigger.value,
            job.status.value,
            job.input_hash,
            job.items_extracted,
            job.items_included,
            job.items_triaged,
            job.items_dropped,
            job.items_failed,
            job.error,
            job.created_at,
            job.completed_at,
        )
        return job

    async def get_job(self, job_id: str) -> PipelineJob | None:
        row = await self.pool.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        return self._row_to_job(row) if row else None

    async def update_job(self, job: PipelineJob) -> None:
        await self.pool.execute(
            """UPDATE jobs SET
                 trigger = $1, status = $2, input_hash = $3,
                 items_extracted = $4, items_included = $5,
                 items_triaged = $6, items_dropped = $7, items_failed = $8,
                 error = $9, completed_at = $10
               WHERE id = $11""",
            job.trigger.value,
            job.status.value,
            job.input_hash,
            job.items_extracted,
            job.items_included,
            job.items_triaged,
            job.items_dropped,
            job.items_failed,
            job.error,
            job.completed_at,
            job.id,
        )

    @staticmethod
    def _row_to_job(row: asyncpg.Record) -> PipelineJob:
        return PipelineJob(
            id=row["id"],
            trigger=row["trigger"],
            status=row["status"],
            input_hash=row["input_hash"],
            items_extracted=row["items_extracted"],
            items_included=row["items_included"],
            items_triaged=row["items_triaged"],
            items_dropped=row["items_dropped"],
            items_failed=row["items_failed"],
            error=row["error"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
