from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from workbench.providers.memory.base import MemoryLayer
from workbench.domain import (
    ExtractedItem,
    IngestionQueueEntry,
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    ItemUpdate,
    JobStatus,
    JobTrigger,
    PipelineJob,
    Priority,
    RawItem,
)
from workbench.pipeline.enrichment import enrich_item
from workbench.pipeline.extraction import extract_items
from workbench.pipeline.filter import (
    decide_from_score,
    gather_facts_and_rules,
    score_and_decide,
)
from workbench.pipeline.triage import generate_card
from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.llm.base import LLMProvider
from workbench.providers.llm.context import llm_call_context
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)

# action (from filter.decide_from_score) -> the coarse verdict the funnel API
# buckets on (see api/funnel.py _DECISION: include/triage -> "triaged", drop ->
# "dropped").
_VERDICT_ACTION = {"auto_include": "include", "auto_drop": "drop", "triage": "triage"}
_OUTCOME = {"auto_include": "included", "auto_drop": "dropped", "triage": "triaged"}


def _funnel_log(action: str, relevance: int, confidence: int) -> list[dict]:
    """Build the per-item funnel trace the Ingestion page renders (one entry per
    stage; shape consumed by api/funnel.py _stage_view)."""
    log = [
        {"stage": "extract", "label": "Extracted", "outcome": "pass"},
        {
            "stage": "relevance",
            "label": "Relevance filter",
            "outcome": _OUTCOME[action],
            "reason": f"relevance {relevance}/100 (confidence {confidence}/100)",
            "confidence": confidence,
        },
    ]
    if action == "auto_include":
        log.append({"stage": "route", "label": "Auto-included", "outcome": "included"})
    elif action == "auto_drop":
        log.append(
            {
                "stage": "route",
                "label": "Auto-dropped (below relevance threshold)",
                "outcome": "dropped",
                "reason": f"relevance {relevance}/100",
            }
        )
    else:
        log.append({"stage": "enrich", "label": "Enriched", "outcome": "pass"})
        log.append(
            {"stage": "triage", "label": "Triage card created", "outcome": "triaged"}
        )
    return log


class PipelineEngine:
    def __init__(
        self,
        stores: Stores,
        memory: MemoryLayer,
        llm: LLMProvider,
        enricher: ContextEnricher,
        queue_scorer=None,
        triage_expiry_days: int = 7,
        content_generators=None,
        record_drop_decisions: bool = False,
        include_threshold: int = 70,
        drop_threshold: int = 30,
        confidence_threshold: int = 70,
        batch_relevance: bool = False,
        max_batch_size: int = 20,
        source_thresholds: dict | None = None,
    ):
        self.stores = stores
        self.memory = memory
        self.llm = llm
        self.enricher = enricher
        self.queue_scorer = queue_scorer
        self.triage_expiry_days = triage_expiry_days
        self.content_generators = content_generators or {}
        self.record_drop_decisions = record_drop_decisions
        self.include_threshold = include_threshold
        self.drop_threshold = drop_threshold
        self.confidence_threshold = confidence_threshold
        self.batch_relevance = batch_relevance
        self.max_batch_size = max_batch_size
        # Per-source relevance/noise thresholds keyed by source_type (==
        # adapter_type), populated at boot and mutated by Targeted Hot-Reload
        # (ADR0013/ADR0044). Absent key -> inherit the global thresholds above,
        # which preserves current routing for every existing source.
        self.source_thresholds: dict = dict(source_thresholds or {})

    def set_source_thresholds(self, source_type: str, relevance) -> None:
        """Install (or clear with ``None``) per-source thresholds for a
        source_type. Mutates in place so the live engine picks the new values up
        on the next routed item -- no restart (ADR0044 hot-reload)."""
        if relevance is None:
            self.source_thresholds.pop(source_type, None)
        else:
            self.source_thresholds[source_type] = relevance

    def thresholds_for(self, source_type: str) -> tuple[int, int, int]:
        """Resolve (include_threshold, drop_threshold, confidence_threshold) for
        a source_type: the per-source override if set, else the global config.
        ``confidence_threshold`` is global (not per-source)."""
        rel = self.source_thresholds.get(source_type)
        if rel is None:
            return (
                self.include_threshold,
                self.drop_threshold,
                self.confidence_threshold,
            )
        return (
            rel.auto_include_threshold,
            rel.drop_below,
            self.confidence_threshold,
        )

    async def enqueue(
        self,
        raw_text: str,
        source_type: str,
        source_id: str | None = None,
        urgency_signals: dict | None = None,
        trigger: JobTrigger = JobTrigger.MANUAL,
        urgency_score: int | None = None,
        source_ref: str | None = None,
        source_url: str | None = None,
    ) -> PipelineJob:
        """Enqueue a raw item. When ``urgency_score`` is provided (e.g. the
        scheduler pre-scored a batch via ``score_urgency_many``), the per-item
        scorer call is skipped (ADR 0048)."""
        if source_id:
            if await self.stores.processed.is_processed(source_type, source_id):
                job = PipelineJob(
                    trigger=trigger,
                    status=JobStatus.COMPLETED,
                    input_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
                )
                await self.stores.jobs.save_job(job)
                return job

        job = PipelineJob(
            trigger=trigger,
            status=JobStatus.QUEUED,
            input_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
        )
        await self.stores.jobs.save_job(job)

        # Birth the root Item now (D3): the autoincrement assigns #123
        # immediately, so the id is stable for the whole journey (incl. the
        # LLM pre-persist window). Status INGESTED -> EXTRACTED once children
        # exist. source_id may be None for ad-hoc enqueues; only born when set.
        # No id is stashed on the queue entry — extraction re-resolves the root
        # by (source_type, source_id) via get_item_by_source_id.
        if source_id:
            # Root carries the source snapshot so the scheduler change-detector
            # diffs the root on re-poll. VERIFIED shape invariant: the ONLY
            # change-detection consumer is scheduler._parse_raw, which reads only
            # raw_data["raw_text"] and json.loads-es it; every in-scope adapter
            # (diff/Phabricator, meta_tasks, google_docs, gmail, github) sets
            # RawItem.raw_text to the JSON-encoded source record, so this single
            # {"raw_text", "source_type", "id"} shape is correct for ALL source
            # types. No adapter reads any other raw_data key for change-detection.
            await self.stores.items.create_root(
                Item(
                    source_type=source_type,
                    source_id=source_id,
                    summary=(raw_text[:200] if raw_text else ""),
                    category=ItemCategory.INFORMATIONAL,
                    origin=ItemOrigin.AUTO_INCLUDED,
                    priority=Priority.PENDING,
                    status=ItemStatus.INGESTED,
                    raw_data={
                        "raw_text": raw_text,
                        "source_type": source_type,
                        "id": source_id,
                    },
                )
            )

        if urgency_score is None:
            urgency_score = 50
            if self.queue_scorer and urgency_signals:
                try:
                    with llm_call_context(
                        origin="queue_scorer",
                        purpose="score_urgency",
                        stage="scoring",
                    ):
                        urgency_score = await self.queue_scorer.score_urgency(
                            raw_text, urgency_signals
                        )
                except Exception as e:
                    logger.warning(f"Queue scorer failed, using default: {e}")

        entry = IngestionQueueEntry(
            raw_content=raw_text,
            source_type=source_type,
            source_id=source_id,
            source_ref=source_ref,
            source_url=source_url,
            urgency_signals=urgency_signals or {},
            urgency_score=urgency_score,
            job_id=job.id,
        )
        await self.stores.ingestion_queue.enqueue(entry)

        if source_id:
            await self.stores.processed.mark_processed(source_type, source_id)

        return job

    async def process_raw_item(self, raw_item: RawItem, job_id: str) -> None:
        job = await self.stores.jobs.get_job(job_id)

        try:
            # Resolve the ingestion root first so the extraction call can link it
            # at true depth (call-time path). The root was born in enqueue.
            root = await self.stores.items.get_item_by_source_id(
                raw_item.source_type, raw_item.id
            )
            extracted = await extract_items(
                self.llm,
                raw_item.raw_text,
                raw_item.source_type,
                root_path=(root.path if root else None),
            )
            if job:
                job.items_extracted = len(extracted)
                await self.stores.jobs.update_job(job)

            # Rebind each extracted item to this raw_item.
            items = [
                ExtractedItem(
                    summary=e.summary,
                    category=e.category,
                    source_context=e.source_context,
                    raw_item=raw_item,
                )
                for e in extracted
            ]

            # Batched relevance scoring (ADR 0048): gather per-item facts/rules
            # concurrently, score all items in one call, then route each item
            # through the single-item helper with its precomputed score.
            # Root already resolved above so each extracted item is nested as a
            # depth-1 child under it (D2/D3).

            precomputed: list[tuple[int, int] | None] = [None] * len(items)
            if self.batch_relevance and items:
                contexts = await asyncio.gather(
                    *(
                        gather_facts_and_rules(
                            self.memory, self.stores.filter_rules, it
                        )
                        for it in items
                    )
                )
                ctx_for_scoring = [
                    (it, facts, rules) for it, (facts, rules) in zip(items, contexts)
                ]
                with llm_call_context(
                    origin="filter",
                    purpose="score_relevance",
                    stage="filter",
                    item_paths=((root.path,) if root else ()),
                ):
                    precomputed = await self.llm.score_relevance_many(
                        ctx_for_scoring, max_batch_size=self.max_batch_size
                    )

            for ext_item, score in zip(items, precomputed):
                try:
                    await self._process_extracted_item(
                        ext_item, job, precomputed=score, root=root
                    )
                except Exception as e:
                    logger.error(f"Failed to process extracted item: {e}")
                    if job:
                        job.items_failed += 1
                        await self.stores.jobs.update_job(job)

            # Children now exist under the root -> move root to EXTRACTED.
            if root is not None and items:
                await self.stores.items.update_item(
                    root.id, ItemUpdate(status=ItemStatus.EXTRACTED)
                )
        except Exception as e:
            logger.error("Pipeline processing failed: %s", e, exc_info=True)
            raise

    async def _process_extracted_item(
        self,
        ext_item: ExtractedItem,
        job: PipelineJob | None,
        precomputed: tuple[int, int] | None = None,
        root: Item | None = None,
    ) -> None:
        # Resolve the routing thresholds for THIS item's source (ADR0044): a
        # per-source override if configured, otherwise the global PipelineConfig
        # thresholds. source_type == adapter_type for ingested items.
        include_t, drop_t, confidence_t = self.thresholds_for(
            ext_item.raw_item.source_type
        )
        if precomputed is not None:
            # Batched path: score already computed by score_relevance_many; apply
            # the resolved thresholds without a second LLM call. Threshold logic
            # lives in filter.decide_from_score (ADR 0048).
            relevance, confidence = precomputed
            action = decide_from_score(
                relevance,
                confidence,
                include_threshold=include_t,
                drop_threshold=drop_t,
                confidence_threshold=confidence_t,
            )
        else:
            action, relevance, confidence = await score_and_decide(
                self.llm,
                self.memory,
                self.stores.filter_rules,
                ext_item,
                include_threshold=include_t,
                drop_threshold=drop_t,
                confidence_threshold=confidence_t,
            )

        funnel_log = _funnel_log(action, relevance, confidence)
        verdict_action = _VERDICT_ACTION[action]

        if action == "auto_include":
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary,
                category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P2,
                status=ItemStatus.ACTIVE,
                raw_data=ext_item.raw_item.model_dump(),
                funnel_log=funnel_log,
                verdict_action=verdict_action,
                verdict_priority=Priority.P2.value,
                verdict_confidence=confidence,
            )
            if root is not None:
                item = await self.stores.items.allocate_child(root, item)
            else:
                await self.stores.items.save_item(item)
            await self.memory.record_pipeline_decision(
                item, "auto_include", f"relevance={relevance}"
            )
            if job:
                job.items_included += 1
                await self.stores.jobs.update_job(job)

        elif action == "auto_drop":
            # Persist the drop (status=DROPPED, excluded from active/triage feeds)
            # so the Ingestion funnel can show what was filtered out and why.
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary,
                category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P3,
                status=ItemStatus.DROPPED,
                raw_data=ext_item.raw_item.model_dump(),
                funnel_log=funnel_log,
                verdict_action=verdict_action,
                verdict_priority=Priority.P3.value,
                verdict_confidence=confidence,
            )
            if root is not None:
                item = await self.stores.items.allocate_child(root, item)
            else:
                await self.stores.items.save_item(item)
            if self.record_drop_decisions:
                await self.memory.record_pipeline_decision(
                    item, "auto_drop", f"relevance={relevance}"
                )
            if job:
                job.items_dropped += 1
                await self.stores.jobs.update_job(job)

        else:
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary,
                category=ext_item.category,
                origin=ItemOrigin.TRIAGED,
                priority=Priority.PENDING,
                status=ItemStatus.PENDING_TRIAGE,
                raw_data=ext_item.raw_item.model_dump(),
                funnel_log=funnel_log,
                verdict_action=verdict_action,
                verdict_priority=Priority.PENDING.value,
                verdict_confidence=confidence,
            )
            if root is not None:
                item = await self.stores.items.allocate_child(root, item)
            else:
                await self.stores.items.save_item(item)

            # Diffs MUST be enriched at "deep" on first triage so the card has
            # curated hunks — the DiffEnricher only fetches them in deep mode
            # (the default "shallow" yields "No code hunks ..."). Re-triage reuses
            # the stored hunks and only re-fetches on code_updated (ADR 0032).
            depth = "deep" if ext_item.raw_item.source_type == "diff" else "shallow"
            enrichment = await enrich_item(
                self.enricher, ext_item, depth, memory=self.memory
            )
            card = await generate_card(
                self.llm,
                ext_item,
                enrichment,
                ext_item.raw_item.source_type,
                memory=self.memory,
                content_generators=self.content_generators,
            )
            card.item_id = item.id
            card.relevance_score = relevance
            card.confidence_score = confidence
            card.expires_at = datetime.now(timezone.utc) + timedelta(
                days=self.triage_expiry_days
            )
            await self.stores.triage.save_card(card)
            if job:
                job.items_triaged += 1
                await self.stores.jobs.update_job(job)
