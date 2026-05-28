from workbench.providers.enrichment.base import ContextEnricher
from workbench.models import ExtractedItem, EnrichmentBudget


class StubEnricher(ContextEnricher):
    async def enrich(self, item, depth, budget):
        return {"calls_made": 0, "time_ms": 0, "context": {}}
