from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from workbench.memory.base import MemoryLayer
from workbench.models import (
    ExtractedItem, IngestionQueueEntry, Item, ItemOrigin, ItemStatus,
    JobStatus, JobTrigger, PipelineJob, Priority, RawItem,
)
from workbench.pipeline.enrichment import enrich_item
from workbench.pipeline.extraction import extract_items
from workbench.pipeline.filter import score_and_decide
from workbench.pipeline.triage import generate_card
from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.llm.base import LLMProvider
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class PipelineEngine:
    def __init__(self, stores: Stores, memory: MemoryLayer, llm: LLMProvider,
                 enricher: ContextEnricher, queue_scorer=None, triage_expiry_days: int = 7):
        self.stores = stores
        self.memory = memory
        self.llm = llm
        self.enricher = enricher
        self.queue_scorer = queue_scorer
        self.triage_expiry_days = triage_expiry_days

    async def enqueue(self, raw_text: str, source_type: str,
                      source_id: str | None = None,
                      urgency_signals: dict | None = None,
                      trigger: JobTrigger = JobTrigger.MANUAL) -> PipelineJob:
        if source_id:
            if await self.stores.processed.is_processed(source_type, source_id):
                job = PipelineJob(trigger=trigger, status=JobStatus.COMPLETED,
                                  input_hash=hashlib.sha256(raw_text.encode()).hexdigest())
                await self.stores.jobs.save_job(job)
                return job

        job = PipelineJob(
            trigger=trigger, status=JobStatus.QUEUED,
            input_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
        )
        await self.stores.jobs.save_job(job)

        urgency_score = 50
        if self.queue_scorer and urgency_signals:
            try:
                urgency_score = await self.queue_scorer.score_urgency(raw_text, urgency_signals)
            except Exception as e:
                logger.warning(f"Queue scorer failed, using default: {e}")

        entry = IngestionQueueEntry(
            raw_content=raw_text, source_type=source_type,
            source_id=source_id,
            urgency_signals=urgency_signals or {},
            urgency_score=urgency_score, job_id=job.id,
        )
        await self.stores.ingestion_queue.enqueue(entry)

        if source_id:
            await self.stores.processed.mark_processed(source_type, source_id)

        return job

    async def process_raw_item(self, raw_item: RawItem, job_id: str) -> None:
        job = await self.stores.jobs.get_job(job_id)

        try:
            extracted = await extract_items(self.llm, raw_item.raw_text, raw_item.source_type)
            if job:
                job.items_extracted = len(extracted)
                await self.stores.jobs.update_job(job)

            for ext_item in extracted:
                ext_item = ExtractedItem(
                    summary=ext_item.summary, category=ext_item.category,
                    source_context=ext_item.source_context, raw_item=raw_item,
                )
                try:
                    await self._process_extracted_item(ext_item, job)
                except Exception as e:
                    logger.error(f"Failed to process extracted item: {e}")
                    if job:
                        job.items_failed += 1
                        await self.stores.jobs.update_job(job)
        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}")
            raise

    async def _process_extracted_item(self, ext_item: ExtractedItem, job: PipelineJob | None) -> None:
        action, relevance, confidence = await score_and_decide(
            self.llm, self.memory, self.stores.filter_rules, ext_item
        )

        if action == "auto_include":
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P2,
                status=ItemStatus.ACTIVE,
            )
            await self.stores.items.save_item(item)
            await self.memory.record_pipeline_decision(item, "auto_include", f"relevance={relevance}")
            if job:
                job.items_included += 1
                await self.stores.jobs.update_job(job)

        elif action == "auto_drop":
            await self.memory.record_pipeline_decision(
                Item(source_type=ext_item.raw_item.source_type, source_id=ext_item.raw_item.id,
                     summary=ext_item.summary, category=ext_item.category,
                     origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P3),
                "auto_drop", f"relevance={relevance}"
            )
            if job:
                job.items_dropped += 1
                await self.stores.jobs.update_job(job)

        else:
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.TRIAGED, priority=Priority.PENDING,
                status=ItemStatus.PENDING_TRIAGE,
            )
            await self.stores.items.save_item(item)

            enrichment = await enrich_item(self.enricher, ext_item)
            card = await generate_card(self.llm, ext_item, enrichment, ext_item.raw_item.source_type)
            card.item_id = item.id
            card.relevance_score = relevance
            card.confidence_score = confidence
            card.expires_at = datetime.now(timezone.utc) + timedelta(days=self.triage_expiry_days)
            await self.stores.triage.save_card(card)
            if job:
                job.items_triaged += 1
                await self.stores.jobs.update_job(job)
