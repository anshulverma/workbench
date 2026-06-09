from workbench.providers.enrichment.base import ContextEnricher
from workbench.domain import ExtractedItem, EnrichmentBudget

async def enrich_item(enricher: ContextEnricher, item: ExtractedItem, depth: str = "shallow", budget: EnrichmentBudget | None = None, *, memory=None) -> dict:
    if budget is None:
        budget = EnrichmentBudget()
    return await enricher.enrich(item, depth, budget, memory=memory)
