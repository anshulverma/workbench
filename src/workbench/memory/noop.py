from pydantic import BaseModel
from workbench.memory.base import MemoryLayer
from workbench.models import (
    TriageCard,
    TriageResponse,
    Item,
    Fact,
    EntityKnowledge,
    Relationship,
)


class NoopMemoryLayer(MemoryLayer):
    memory_type = "noop"

    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None):
        self.config = config

    async def record_triage(self, card, response):
        pass

    async def record_entity(self, entity_type, entity_id, facts):
        pass

    async def record_pipeline_decision(self, item, decision, reason):
        pass

    async def query_preferences(self, context):
        return []

    async def query_entity(self, entity_type, entity_id):
        return None

    async def query_relationships(self, entity_type, entity_id):
        return []

    async def is_available(self):
        return False

    async def list_facts(self):
        return []

    async def add_fact(self, content, source="manual"):
        raise NotImplementedError("memory layer not configured")

    async def delete_fact(self, fact_id):
        raise NotImplementedError("memory layer not configured")

    async def update_fact(self, fact_id, content):
        raise NotImplementedError("memory layer not configured")
