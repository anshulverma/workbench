from abc import ABC, abstractmethod
from server.models import ExtractedItem, EnrichmentBudget


class ContextEnricher(ABC):
    @abstractmethod
    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget) -> dict: ...
