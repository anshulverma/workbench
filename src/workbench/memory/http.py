from __future__ import annotations

import logging
from datetime import datetime

import httpx
from pydantic import BaseModel

from workbench.memory.base import MemoryLayer
from workbench.domain import (
    EntityKnowledge,
    Fact,
    Item,
    Relationship,
    TriageCard,
    TriageResponse,
)

logger = logging.getLogger(__name__)


class HttpMemoryLayer(MemoryLayer):
    memory_type = "http"

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

    async def record_entity(
        self, entity_type: str, entity_id: str, facts: dict
    ) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/entity",
                json={
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "facts": facts,
                },
            )
        except Exception as e:
            logger.warning("Memory service record_entity failed: %s", e)

    async def record_pipeline_decision(
        self, item: Item, decision: str, reason: str
    ) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/decision",
                json={
                    "item_summary": item.summary,
                    "decision": decision,
                    "reason": reason,
                    "source_type": item.source_type,
                },
            )
        except Exception as e:
            logger.warning("Memory service record_pipeline_decision failed: %s", e)

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/preferences",
                params={"context": context},
            )
            resp.raise_for_status()
            data = resp.json()
            return [self._parse_fact(f) for f in data.get("facts", [])]
        except Exception as e:
            logger.warning("Memory service query_preferences failed: %s", e)
            return []

    @staticmethod
    def _parse_fact(f: dict) -> Fact:
        ts = f.get("timestamp")
        return Fact(
            id=f.get("id"),
            content=f["content"],
            source=f.get("source", "graphiti"),
            timestamp=datetime.fromisoformat(ts) if ts else None,
        )

    async def list_facts(self) -> list[Fact]:
        try:
            resp = await self._client.get(f"{self._base_url}/facts")
            resp.raise_for_status()
            data = resp.json()
            return [self._parse_fact(f) for f in data.get("facts", [])]
        except Exception as e:
            logger.warning("Memory service list_facts failed: %s", e)
            return []

    async def add_fact(self, content: str, source: str = "manual") -> Fact:
        # Manual facts carry a distinct origin marker so the synthesis pipeline
        # does not overwrite them and the UI can distinguish authored from
        # learned facts (ADR0045). Failures propagate so the API surfaces them.
        resp = await self._client.post(
            f"{self._base_url}/facts",
            json={"content": content, "source": source},
        )
        resp.raise_for_status()
        return self._parse_fact(resp.json())

    async def delete_fact(self, fact_id: str) -> None:
        resp = await self._client.delete(f"{self._base_url}/facts/{fact_id}")
        resp.raise_for_status()

    async def update_fact(self, fact_id: str, content: str) -> None:
        resp = await self._client.patch(
            f"{self._base_url}/facts/{fact_id}", json={"content": content}
        )
        resp.raise_for_status()

    async def query_entity(
        self, entity_type: str, entity_id: str
    ) -> EntityKnowledge | None:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/entity",
                params={"entity_type": entity_type, "entity_id": entity_id},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return EntityKnowledge(
                entity_type=data["entity_type"],
                entity_id=data["entity_id"],
                facts=data.get("facts", {}),
            )
        except Exception as e:
            logger.warning("Memory service query_entity failed: %s", e)
            return None

    async def query_relationships(
        self, entity_type: str, entity_id: str
    ) -> list[Relationship]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/relationships",
                params={"entity_type": entity_type, "entity_id": entity_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                Relationship(
                    from_entity=r["from_entity"],
                    to_entity=r["to_entity"],
                    relation=r["relation"],
                )
                for r in data.get("relationships", [])
            ]
        except Exception as e:
            logger.warning("Memory service query_relationships failed: %s", e)
            return []

    async def is_available(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception:
            logger.debug("Memory service availability check failed")
            return False

    async def close(self) -> None:
        await self._client.aclose()
