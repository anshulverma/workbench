from __future__ import annotations

from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.enrichment.stub import StubEnricher
from workbench.domain import ExtractedItem, EnrichmentBudget


class CompositeEnricher(ContextEnricher):
    def __init__(
        self,
        enrichers: dict[str, ContextEnricher],
        default: ContextEnricher | None = None,
        budgets: dict[str, EnrichmentBudget] | None = None,
    ):
        self.enrichers = enrichers
        self.default = default or StubEnricher()
        self.budgets = budgets or {}

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        source_type = item.raw_item.source_type
        enricher = self.enrichers.get(source_type, self.default)
        effective_budget = self.budgets.get(source_type, budget)
        return await enricher.enrich(item, depth, effective_budget, memory=memory)

    async def close(self) -> None:
        seen = set()
        for enricher in self.enrichers.values():
            eid = id(enricher)
            if eid not in seen:
                seen.add(eid)
                await enricher.close()
        if id(self.default) not in seen:
            await self.default.close()
