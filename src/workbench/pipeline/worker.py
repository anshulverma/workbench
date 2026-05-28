from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from workbench.models import JobStatus, RawItem
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class IngestionQueueWorker:
    def __init__(self, stores: Stores, pipeline, concurrency: int = 2):
        self.stores = stores
        self.pipeline = pipeline
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Ingestion queue worker started (concurrency={self.concurrency})")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        recovered = await self.stores.ingestion_queue.recover_stuck()
        if recovered:
            logger.info(f"Recovered {recovered} stuck queue entries")

        while self._running:
            try:
                entries = await self.stores.ingestion_queue.dequeue(limit=self.concurrency)
                if not entries:
                    await asyncio.sleep(2)
                    continue

                tasks = [self._process_entry(entry) for entry in entries]
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
                await asyncio.sleep(5)

    async def _process_entry(self, entry):
        async with self._semaphore:
            try:
                raw_item = RawItem(
                    id=entry.source_id or entry.id,
                    source_type=entry.source_type,
                    source_label="",
                    raw_text=entry.raw_content,
                    urgency_signals=entry.urgency_signals,
                )

                job = await self.stores.jobs.get_job(entry.job_id)
                if job and job.status.value == "queued":
                    job.status = JobStatus.RUNNING
                    await self.stores.jobs.update_job(job)

                await self.pipeline.process_raw_item(raw_item, entry.job_id)
                await self.stores.ingestion_queue.mark_completed(entry.id)

                if job:
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)
                    await self.stores.jobs.update_job(job)

            except Exception as e:
                logger.error(f"Failed to process queue entry {entry.id}: {e}")
                await self.stores.ingestion_queue.mark_failed(entry.id, str(e))

                job = await self.stores.jobs.get_job(entry.job_id)
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    await self.stores.jobs.update_job(job)
