from server.storage.base import JobStore
from server.models import PipelineJob


class SqliteJobStore(JobStore):
    def __init__(self, db):
        self.db = db

    async def save_job(self, job: PipelineJob) -> PipelineJob:
        await self.db.execute(
            "INSERT INTO jobs (id, trigger, status, input_hash, items_extracted, items_included, items_triaged, items_dropped, items_failed, error, created_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
                job.created_at.isoformat(),
                job.completed_at.isoformat() if job.completed_at else None,
            ),
        )
        await self.db.commit()
        return job

    async def get_job(self, job_id: str) -> PipelineJob | None:
        cursor = await self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return self._row_to_job(row) if row else None

    async def update_job(self, job: PipelineJob) -> None:
        await self.db.execute(
            "UPDATE jobs SET trigger = ?, status = ?, input_hash = ?, items_extracted = ?, items_included = ?, items_triaged = ?, items_dropped = ?, items_failed = ?, error = ?, completed_at = ? WHERE id = ?",
            (
                job.trigger.value,
                job.status.value,
                job.input_hash,
                job.items_extracted,
                job.items_included,
                job.items_triaged,
                job.items_dropped,
                job.items_failed,
                job.error,
                job.completed_at.isoformat() if job.completed_at else None,
                job.id,
            ),
        )
        await self.db.commit()

    def _row_to_job(self, row) -> PipelineJob:
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
