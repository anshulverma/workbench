from abc import ABC, abstractmethod
from workbench.domain import ExtractedItem, EnrichmentBudget


class ContextEnricher(ABC):
    @abstractmethod
    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None) -> dict: ...

    async def close(self) -> None:
        pass
