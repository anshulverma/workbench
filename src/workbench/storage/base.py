# server/storage/base.py
from abc import ABC, abstractmethod
from workbench.models import (
    Item, ItemFilters, ItemUpdate,
    TriageCard, TriageResponse,
    Plan, PlanFilters, PlanUpdate,
    InteractionEntry,
    FilterRule,
    EnrichmentTrace, TraceFilters,
    SourceConfig, SourceConfigUpdate,
    PipelineJob,
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

class TriageStore(ABC):
    @abstractmethod
    async def get_pending(self) -> list[TriageCard]: ...
    @abstractmethod
    async def save_card(self, card: TriageCard) -> TriageCard: ...
    @abstractmethod
    async def record_response(self, card_id: str, response: TriageResponse) -> None: ...
    @abstractmethod
    async def get_card(self, card_id: str) -> TriageCard | None: ...

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

class SourceConfigStore(ABC):
    @abstractmethod
    async def get_sources(self) -> list[SourceConfig]: ...
    @abstractmethod
    async def save_source(self, source: SourceConfig) -> SourceConfig: ...
    @abstractmethod
    async def update_source(self, source_id: str, updates: SourceConfigUpdate) -> SourceConfig: ...
    @abstractmethod
    async def delete_source(self, source_id: str) -> None: ...

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

class Stores:
    """Container for all repository instances."""
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
