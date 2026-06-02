from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from workbench.memory.base import MemoryLayer
from workbench.models import (
    EntityKnowledge,
    Fact,
    Item,
    Relationship,
    TriageCard,
    TriageResponse,
)

logger = logging.getLogger(__name__)


class HttpMemoryLayer(MemoryLayer):
    class ProviderConfig(BaseModel):
        base_url: str = "http://localhost:8422"
        timeout_seconds: int = 5

    def __init__(self, config: ProviderConfig = None):
        if config is None:
            config = self.ProviderConfig()
        self._base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def record_triage(self, card: TriageCard, response: TriageResponse) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/triage",
                json={
                    "card": card.model_dump(),
                    "response": response.model_dump(),
                },
            )
        except Exception as e:
            logger.warning("Memory service record_triage failed: %s", e)

    async def record_entity(self, entity_type: str, entity_id: str, facts: dict) -> None:
        pass

    async def record_pipeline_decision(self, item: Item, decision: str, reason: str) -> None:
        pass

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/preferences",
                params={"context": context},
            )
            resp.raise_for_status()
            data = resp.json()
            return [Fact(content=f["content"], source=f.get("source", "graphiti")) for f in data.get("facts", [])]
        except Exception as e:
            logger.warning("Memory service query_preferences failed: %s", e)
            return []

    async def query_entity(self, entity_type: str, entity_id: str) -> EntityKnowledge | None:
        return None

    async def query_relationships(self, entity_type: str, entity_id: str) -> list[Relationship]:
        return []

    async def is_available(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
