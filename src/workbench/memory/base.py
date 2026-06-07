from abc import ABC, abstractmethod
from workbench.models import (
    TriageCard,
    TriageResponse,
    Item,
    Fact,
    EntityKnowledge,
    Relationship,
)


class MemoryLayer(ABC):
    # Short label for the active memory backend (used by the facts envelope).
    memory_type: str = "unknown"

    @abstractmethod
    async def record_triage(
        self, card: TriageCard, response: TriageResponse
    ) -> None: ...
    @abstractmethod
    async def record_entity(
        self, entity_type: str, entity_id: str, facts: dict
    ) -> None: ...
    @abstractmethod
    async def record_pipeline_decision(
        self, item: Item, decision: str, reason: str
    ) -> None: ...
    @abstractmethod
    async def query_preferences(self, context: str) -> list[Fact]: ...
    @abstractmethod
    async def query_entity(
        self, entity_type: str, entity_id: str
    ) -> EntityKnowledge | None: ...
    @abstractmethod
    async def query_relationships(
        self, entity_type: str, entity_id: str
    ) -> list[Relationship]: ...
    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def list_facts(self) -> list[Fact]: ...
    @abstractmethod
    async def delete_fact(self, fact_id: str) -> None: ...
    @abstractmethod
    async def update_fact(self, fact_id: str, content: str) -> None: ...

    async def close(self) -> None:
        pass
