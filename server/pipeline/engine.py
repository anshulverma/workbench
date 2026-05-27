import hashlib
import logging
from datetime import datetime
from server.storage.base import Stores
from server.memory.base import MemoryLayer
from server.providers.llm.base import LLMProvider
from server.providers.enrichment.base import ContextEnricher
from server.pipeline.extraction import extract_items
from server.pipeline.filter import score_and_decide
from server.pipeline.enrichment import enrich_item
from server.pipeline.triage import generate_card
from server.models import (
    RawItem, Item, ItemCategory, ItemOrigin, Priority,
    PipelineJob, JobTrigger, JobStatus, InteractionEntry,
)

logger = logging.getLogger(__name__)

class PipelineEngine:
    def __init__(self, stores: Stores, memory: MemoryLayer, llm: LLMProvider, enricher: ContextEnricher):
        self.stores = stores
        self.memory = memory
        self.llm = llm
        self.enricher = enricher

    async def process(self, raw_text: str, source_type: str, trigger: JobTrigger = JobTrigger.MANUAL) -> PipelineJob:
        job = PipelineJob(trigger=trigger, input_hash=hashlib.sha256(raw_text.encode()).hexdigest())
        await self.stores.jobs.save_job(job)
        job.status = JobStatus.RUNNING
        await self.stores.jobs.update_job(job)

        try:
            extracted = await extract_items(self.llm, raw_text, source_type)
            job.items_extracted = len(extracted)

            for ext_item in extracted:
                try:
                    await self._process_extracted_item(ext_item, job)
                except Exception as e:
                    logger.error(f"Failed to process item: {e}")
                    job.items_failed += 1

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()

        await self.stores.jobs.update_job(job)
        return job

    async def _process_extracted_item(self, ext_item, job: PipelineJob):
        action, relevance, confidence = await score_and_decide(
            self.llm, self.memory, self.stores.filter_rules, ext_item
        )

        if action == "auto_include":
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary,
                category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P2,
            )
            await self.stores.items.save_item(item)
            await self.memory.record_pipeline_decision(item, "auto_include", f"relevance={relevance}")
            job.items_included += 1

        elif action == "auto_drop":
            await self.memory.record_pipeline_decision(
                Item(source_type=ext_item.raw_item.source_type, source_id=ext_item.raw_item.id,
                     summary=ext_item.summary, category=ext_item.category,
                     origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P3),
                "auto_drop", f"relevance={relevance}"
            )
            job.items_dropped += 1

        else:  # triage
            enrichment = await enrich_item(self.enricher, ext_item)
            card = await generate_card(self.llm, ext_item, enrichment, ext_item.raw_item.source_type)
            await self.stores.triage.save_card(card)
            job.items_triaged += 1
