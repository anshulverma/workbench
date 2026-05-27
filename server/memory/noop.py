from server.memory.base import MemoryLayer
from server.models import TriageCard, TriageResponse, Item, Fact, EntityKnowledge, Relationship


class NoopMemoryLayer(MemoryLayer):
    async def record_triage(self, card, response): pass
    async def record_entity(self, entity_type, entity_id, facts): pass
    async def record_pipeline_decision(self, item, decision, reason): pass
    async def query_preferences(self, context): return []
    async def query_entity(self, entity_type, entity_id): return None
    async def query_relationships(self, entity_id): return []
    async def is_available(self): return False
