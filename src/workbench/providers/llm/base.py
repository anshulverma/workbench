from abc import ABC, abstractmethod
from workbench.models import ExtractedItem, FilterRule, TriageCard, Fact


class LLMProvider(ABC):
    @abstractmethod
    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]: ...
    @abstractmethod
    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]: ...
    @abstractmethod
    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard: ...
