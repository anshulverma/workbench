from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from workbench.storage.ingestion_runs import IngestionRunStore
from workbench.domain.llm_calls import LlmCallRecord
from workbench.domain.messages import Message
from workbench.domain import (
    EnricherConfig,
    EnrichmentTrace,
    FeedbackCorrection,
    FilterRule,
    FilterTuningTask,
    IngestionQueueEntry,
    InteractionEntry,
    Item,
    ItemFilters,
    ItemUpdate,
    LoopBackConfig,
    PipelineJob,
    RawItem,
    Plan,
    PlanFilters,
    PlanUpdate,
    SourceConfig,
    SourceConfigUpdate,
    TraceFilters,
    TriageCard,
    TriageResponse,
)


class ItemStore(ABC):
    @abstractmethod
    async def get_items(self, filters: ItemFilters) -> list[Item]: ...
    @abstractmethod
    async def get_item(self, item_id: int) -> Item | None: ...
    @abstractmethod
    async def save_item(self, item: Item) -> Item: ...
    @abstractmethod
    async def create_root(self, item: Item) -> Item:
        """Insert a depth-0 item and set path = str(id) (D1/D3)."""
        ...

    @abstractmethod
    async def allocate_child(self, parent: Item, child: Item) -> Item:
        """Insert a child: seq = MAX(seq)+1 over siblings, path = parent.path.seq."""
        ...

    @abstractmethod
    async def get_by_path(self, path: str) -> Item | None: ...
    @abstractmethod
    async def get_ancestors(self, item: Item) -> list[Item]:
        """Root-first chain of ancestors of ``item`` (excludes item itself)."""
        ...

    @abstractmethod
    async def get_children(self, parent_id: int) -> list[tuple[Item, bool]]:
        """Direct children of ``parent_id``, each with a has_children flag."""
        ...

    @abstractmethod
    async def update_item(self, item_id: int, updates: ItemUpdate) -> Item: ...
    @abstractmethod
    async def archive_item(self, item_id: int) -> None: ...
    @abstractmethod
    async def get_items_by_source(self, source_type: str) -> list[Item]: ...
    @abstractmethod
    async def get_item_by_source_id(
        self, source_type: str, source_id: str
    ) -> Item | None: ...
    @abstractmethod
    async def get_active_by_source(self, source_type: str) -> list[Item]: ...
    @abstractmethod
    async def update_raw_data(self, item_id: int, raw_item: RawItem) -> None: ...
    @abstractmethod
    async def delete_older_than(self, status: str, days: int) -> int:
        """Delete items with given status older than days. Returns count deleted."""
        ...

    @abstractmethod
    async def count_by_status(self) -> dict[str, int]:
        """COUNT(*) GROUP BY status."""
        ...

    @abstractmethod
    async def count_by_priority(self) -> dict[str, int]:
        """COUNT(*) GROUP BY priority."""
        ...

    @abstractmethod
    async def count_by_category(self) -> dict[str, int]:
        """COUNT(*) GROUP BY category."""
        ...

    @abstractmethod
    async def count_by_source(self) -> dict[str, int]:
        """COUNT(*) GROUP BY source_type (items_stored per source)."""
        ...

    @abstractmethod
    async def count_created_since(self, hours: int) -> int:
        """Count items with created_at within the last ``hours`` hours."""
        ...

    @abstractmethod
    async def auto_resolved_counts(self, hours: int) -> tuple[int, int]:
        """(auto_included, total) item counts created within the window."""
        ...

    @abstractmethod
    async def created_timeseries(
        self, window: int, bucket: str
    ) -> list[tuple[datetime, int]]:
        """Items created per bucket over the window (date_trunc grouped)."""
        ...

    @abstractmethod
    async def completed_timeseries(
        self, window: int, bucket: str
    ) -> list[tuple[datetime, int]]:
        """Items completed (completed_at) per bucket over the window."""
        ...

    @abstractmethod
    async def items_recent(self, limit: int) -> list[Item]:
        """Most recently created items, ORDER BY created_at DESC."""
        ...


class TriageStore(ABC):
    @abstractmethod
    async def get_pending(self) -> list[TriageCard]: ...
    @abstractmethod
    async def get_next_unsent(self) -> TriageCard | None: ...
    @abstractmethod
    async def save_card(self, card: TriageCard) -> TriageCard: ...
    @abstractmethod
    async def update_card(self, card: TriageCard) -> None: ...
    @abstractmethod
    async def record_response(self, card_id: int, response: TriageResponse) -> None: ...
    @abstractmethod
    async def get_card(self, card_id: int) -> TriageCard | None: ...
    @abstractmethod
    async def get_card_by_item_id(self, item_id: int) -> TriageCard | None: ...
    @abstractmethod
    async def clear_deferral(self, card_id: int) -> None: ...
    @abstractmethod
    async def expire_old_cards(self, expiry_days: int) -> int: ...
    @abstractmethod
    async def count_sent_today(self) -> int: ...
    @abstractmethod
    async def defer_card(self, card_id: int, until: datetime) -> None: ...
    @abstractmethod
    async def get_deferred_ready(self) -> list[TriageCard]: ...
    @abstractmethod
    async def delete_older_than(self, status: str, days: int) -> int:
        """Delete triage cards with given status older than days. Returns count deleted."""
        ...

    @abstractmethod
    async def avg_triage_seconds(self) -> float | None:
        """Average responded_at - sent_at over responded cards, or None."""
        ...

    @abstractmethod
    async def enqueued_timeseries(
        self, window: int, bucket: str
    ) -> list[tuple[datetime, int]]:
        """Cards entering the triage queue (created_at) per bucket over window."""
        ...

    @abstractmethod
    async def triaged_timeseries(
        self, window: int, bucket: str
    ) -> list[tuple[datetime, int]]:
        """Cards triaged (responded_at) per bucket over the window."""
        ...


class PlanStore(ABC):
    @abstractmethod
    async def get_plans(self, filters: PlanFilters) -> list[Plan]: ...
    @abstractmethod
    async def save_plan(self, plan: Plan) -> Plan: ...
    @abstractmethod
    async def update_plan(self, plan_id: int, updates: PlanUpdate) -> Plan: ...


class InteractionStore(ABC):
    @abstractmethod
    async def append(self, entry: InteractionEntry) -> None: ...
    @abstractmethod
    async def get_since(self, cursor: int, limit: int) -> list[InteractionEntry]: ...
    @abstractmethod
    async def count(self) -> int: ...
    @abstractmethod
    async def get_all(self) -> list[InteractionEntry]: ...


class FilterRuleStore(ABC):
    @abstractmethod
    async def get_rules(self) -> list[FilterRule]: ...
    @abstractmethod
    async def add_rule(self, rule: FilterRule) -> FilterRule: ...
    @abstractmethod
    async def get_source_rules(self, source_type: str) -> list[FilterRule]: ...
    @abstractmethod
    async def update_rule(self, rule_id: int, updates: dict) -> FilterRule: ...
    @abstractmethod
    async def delete_rule(self, rule_id: int) -> None: ...
    @abstractmethod
    async def reorder_rules(self, rule_ids: list[int]) -> None:
        """Set order_index for each rule based on position in the list."""
        ...


class EnrichmentTraceStore(ABC):
    @abstractmethod
    async def log_trace(self, trace: EnrichmentTrace) -> None: ...
    @abstractmethod
    async def get_traces(self, filters: TraceFilters) -> list[EnrichmentTrace]: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int:
        """Delete enrichment traces older than days. Returns count deleted."""
        ...


class SourceConfigStore(ABC):
    @abstractmethod
    async def get_sources(self) -> list[SourceConfig]: ...
    @abstractmethod
    async def get_source(self, source_id: str) -> SourceConfig | None: ...
    @abstractmethod
    async def upsert_source(self, source: SourceConfig) -> SourceConfig: ...
    @abstractmethod
    async def update_source(
        self, source_id: str, updates: SourceConfigUpdate
    ) -> SourceConfig: ...


class ProcessedStore(ABC):
    @abstractmethod
    async def is_processed(self, source_type: str, source_id: str) -> bool: ...
    @abstractmethod
    async def mark_processed(self, source_type: str, source_id: str) -> None: ...


class ConfigStore(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...
    @abstractmethod
    async def set(self, key: str, value: str) -> None: ...
    @abstractmethod
    async def get_all(self) -> dict[str, str]: ...


class JobStore(ABC):
    @abstractmethod
    async def save_job(self, job: PipelineJob) -> PipelineJob: ...
    @abstractmethod
    async def get_job(self, job_id: int) -> PipelineJob | None: ...
    @abstractmethod
    async def update_job(self, job: PipelineJob) -> None: ...
    @abstractmethod
    async def list_jobs(
        self, limit: int, offset: int, status: str | None = None
    ) -> list[PipelineJob]:
        """Jobs page, ORDER BY created_at DESC, optionally filtered by status."""
        ...

    @abstractmethod
    async def count_jobs(self, status: str | None = None) -> int:
        """COUNT of jobs, optionally filtered by status."""
        ...


class IngestionQueueStore(ABC):
    @abstractmethod
    async def enqueue(self, entry: IngestionQueueEntry) -> IngestionQueueEntry: ...
    @abstractmethod
    async def dequeue(self, limit: int = 1) -> list[IngestionQueueEntry]: ...
    @abstractmethod
    async def mark_completed(self, entry_id: int) -> None: ...
    @abstractmethod
    async def mark_failed(self, entry_id: int, error: str) -> None: ...
    @abstractmethod
    async def get_dead_letters(self) -> list[IngestionQueueEntry]: ...
    @abstractmethod
    async def retry_dead_letter(self, entry_id: int) -> None: ...
    @abstractmethod
    async def purge_dead_letter(self, entry_id: int) -> None: ...
    @abstractmethod
    async def recover_stuck(self) -> int: ...
    @abstractmethod
    async def queue_depth(self) -> int: ...
    @abstractmethod
    async def count_dead_letters(self) -> int:
        """COUNT of dead_letter rows (never a full-row scan)."""
        ...

    @abstractmethod
    async def count_by_status(self) -> dict[str, int]:
        """COUNT(*) GROUP BY status."""
        ...

    @abstractmethod
    async def count_by_source(self) -> dict[str, int]:
        """COUNT(*) GROUP BY source_type for in-flight (queued/processing) rows."""
        ...

    @abstractmethod
    async def delete_dead_letters_older_than(self, days: int) -> int:
        """Delete dead letter entries older than days. Returns count deleted."""
        ...


class FeedbackStore(ABC):
    @abstractmethod
    async def get_corrections(
        self, item_id: int | None = None
    ) -> list[FeedbackCorrection]: ...
    @abstractmethod
    async def add_correction(
        self, correction: FeedbackCorrection
    ) -> FeedbackCorrection: ...
    @abstractmethod
    async def delete_correction(self, correction_id: int) -> None: ...
    @abstractmethod
    async def get_tasks(self, status: str | None = None) -> list[FilterTuningTask]: ...
    @abstractmethod
    async def add_task(self, task: FilterTuningTask) -> FilterTuningTask: ...
    @abstractmethod
    async def update_task(self, task_id: int, status: str) -> FilterTuningTask: ...
    @abstractmethod
    async def delete_task(self, task_id: int) -> None: ...


class EnrichersStore(ABC):
    @abstractmethod
    async def get_enrichers(self) -> list[EnricherConfig]: ...
    @abstractmethod
    async def get_enricher(self, enricher_id: int) -> EnricherConfig | None: ...
    @abstractmethod
    async def upsert_enricher(self, enricher: EnricherConfig) -> EnricherConfig: ...
    @abstractmethod
    async def delete_enricher(self, enricher_id: int) -> None: ...


class LoopBacksStore(ABC):
    @abstractmethod
    async def get_loopbacks(self) -> list[LoopBackConfig]: ...
    @abstractmethod
    async def get_loopback(self, loopback_id: int) -> LoopBackConfig | None: ...
    @abstractmethod
    async def upsert_loopback(self, loopback: LoopBackConfig) -> LoopBackConfig: ...
    @abstractmethod
    async def delete_loopback(self, loopback_id: int) -> None: ...


class FunnelTracesStore(ABC):
    @abstractmethod
    async def get_stages(self, item_id: int) -> list[dict]: ...
    @abstractmethod
    async def log_stage(self, item_id: int, stage: dict) -> None: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int: ...


class FunnelOrderStore(ABC):
    @abstractmethod
    async def get_order(self) -> list[dict]: ...
    @abstractmethod
    async def set_order(self, entries: list[dict]) -> None: ...
    @abstractmethod
    async def toggle_stage(self, stage_id: str, enabled: bool) -> None: ...


@dataclass(frozen=True)
class EntityLink:
    entity_type: str
    entity_id: int | None
    item_id: int
    item_path: str
    correlation_id: str | None = None
    created_at: datetime | None = None


class EntityLinkStore(ABC):
    @abstractmethod
    async def record(
        self, entity_type: str, entity_id: int, item_paths: list[str]
    ) -> None:
        """Idempotent upsert. Resolves each path to its item_id in-DB and writes
        one row per resolved path (ON CONFLICT DO NOTHING). Empty item_paths is a
        no-op; an unknown path resolves to no row."""
        ...

    @abstractmethod
    async def record_by_correlation(
        self, entity_type: str, correlation_id: str, item_paths: list[str]
    ) -> None:
        """Post-persist path. Same in-DB path->id resolve, but entity_id is left
        NULL and correlation_id is stamped."""
        ...

    @abstractmethod
    async def unlink_entity(self, entity_type: str, entity_id: int) -> int:
        """Delete all link rows for one entity (retention cascade). Returns count."""
        ...

    @abstractmethod
    async def for_item(self, path: str, *, subtree: bool = False) -> list[EntityLink]:
        """All links touching ``path`` (and descendants when subtree=True)."""
        ...

    @abstractmethod
    async def for_entity(self, entity_type: str, entity_id: int) -> list[EntityLink]:
        """All item links an entity consumed."""
        ...


class MessageStore(ABC):
    @abstractmethod
    async def save(self, message: Message) -> Message: ...
    @abstractmethod
    async def get_by_id(self, message_id: int) -> Message | None: ...
    @abstractmethod
    async def list_recent(self, limit: int) -> list[Message]: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int:
        """Delete messages older than days. Returns count deleted."""
        ...


class LlmCallStore(ABC):
    @abstractmethod
    async def save_many(
        self, records: list[LlmCallRecord], *, entity_links=None
    ) -> None: ...
    @abstractmethod
    async def list_calls(
        self,
        *,
        limit: int,
        before: tuple[datetime, int] | None = None,
        stage: str | None = None,
        status: str | None = None,
        origin: str | None = None,
        q: str | None = None,
    ) -> list[LlmCallRecord]: ...
    @abstractmethod
    async def get_by_id(self, call_id: int) -> LlmCallRecord | None: ...
    @abstractmethod
    async def count_since(self, since: datetime) -> int: ...
    @abstractmethod
    async def metrics_24h(self) -> dict: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int: ...
    @abstractmethod
    async def prune_to_max_rows(self, max_rows: int) -> int: ...


class Stores:
    def __init__(
        self,
        items: ItemStore,
        triage: TriageStore,
        plans: PlanStore,
        interactions: InteractionStore,
        filter_rules: FilterRuleStore,
        enrichment: EnrichmentTraceStore,
        sources: SourceConfigStore,
        processed: ProcessedStore,
        config: ConfigStore,
        jobs: JobStore,
        ingestion_queue: IngestionQueueStore,
        ingestion_runs: IngestionRunStore,
        close_fn=None,
        *,
        feedback: FeedbackStore | None = None,
        enrichers: EnrichersStore | None = None,
        loopbacks: LoopBacksStore | None = None,
        funnel_traces: FunnelTracesStore | None = None,
        funnel_order: FunnelOrderStore | None = None,
        llm_calls: LlmCallStore | None = None,
        entity_links: EntityLinkStore | None = None,
        messages: MessageStore | None = None,
    ):
        self.items = items
        self.triage = triage
        self.plans = plans
        self.interactions = interactions
        self.filter_rules = filter_rules
        self.enrichment = enrichment
        self.sources = sources
        self.processed = processed
        self.config = config
        self.jobs = jobs
        self.ingestion_queue = ingestion_queue
        self.ingestion_runs = ingestion_runs
        self._close_fn = close_fn
        self.feedback = feedback
        self.enrichers = enrichers
        self.loopbacks = loopbacks
        self.funnel_traces = funnel_traces
        self.funnel_order = funnel_order
        self.llm_calls = llm_calls
        self.entity_links = entity_links
        self.messages = messages

    async def close(self):
        if self._close_fn:
            await self._close_fn()
