from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from workbench.storage.ingestion_runs import IngestionRunStore
from workbench.domain import (
    EnrichmentTrace,
    FilterRule,
    IngestionQueueEntry,
    InteractionEntry,
    Item,
    ItemFilters,
    ItemUpdate,
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
    async def get_item(self, item_id: str) -> Item | None: ...
    @abstractmethod
    async def save_item(self, item: Item) -> Item: ...
    @abstractmethod
    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item: ...
    @abstractmethod
    async def archive_item(self, item_id: str) -> None: ...
    @abstractmethod
    async def get_items_by_source(self, source_type: str) -> list[Item]: ...
    @abstractmethod
    async def get_item_by_source_id(
        self, source_type: str, source_id: str
    ) -> Item | None: ...
    @abstractmethod
    async def get_active_by_source(self, source_type: str) -> list[Item]: ...
    @abstractmethod
    async def update_raw_data(self, item_id: str, raw_item: RawItem) -> None: ...
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
    async def record_response(self, card_id: str, response: TriageResponse) -> None: ...
    @abstractmethod
    async def get_card(self, card_id: str) -> TriageCard | None: ...
    @abstractmethod
    async def get_card_by_item_id(self, item_id: str) -> TriageCard | None: ...
    @abstractmethod
    async def clear_deferral(self, card_id: str) -> None: ...
    @abstractmethod
    async def expire_old_cards(self, expiry_days: int) -> int: ...
    @abstractmethod
    async def count_sent_today(self) -> int: ...
    @abstractmethod
    async def defer_card(self, card_id: str, until: datetime) -> None: ...
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


class PlanStore(ABC):
    @abstractmethod
    async def get_plans(self, filters: PlanFilters) -> list[Plan]: ...
    @abstractmethod
    async def save_plan(self, plan: Plan) -> Plan: ...
    @abstractmethod
    async def update_plan(self, plan_id: str, updates: PlanUpdate) -> Plan: ...


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
    async def get_job(self, job_id: str) -> PipelineJob | None: ...
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
    async def mark_completed(self, entry_id: str) -> None: ...
    @abstractmethod
    async def mark_failed(self, entry_id: str, error: str) -> None: ...
    @abstractmethod
    async def get_dead_letters(self) -> list[IngestionQueueEntry]: ...
    @abstractmethod
    async def retry_dead_letter(self, entry_id: str) -> None: ...
    @abstractmethod
    async def purge_dead_letter(self, entry_id: str) -> None: ...
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

    async def close(self):
        if self._close_fn:
            await self._close_fn()
