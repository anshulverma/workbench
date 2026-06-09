from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.domain import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GChatEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "chat":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[dict[str, str]] = []
        calls_made = 0

        # Extract participant entities (deduplicated)
        seen_senders: set[str] = set()
        for msg in raw.get("messages", []):
            sender_name = msg.get("sender_name", "")
            sender_display = msg.get("sender_display", "")
            if sender_name and sender_name not in seen_senders:
                seen_senders.add(sender_name)
                entity_refs.append({"type": "person", "id": f"gchat:{sender_name}"})
                if memory:
                    try:
                        await memory.record_entity(
                            "person",
                            f"gchat:{sender_name}",
                            {"display_name": sender_display, "chat_id": sender_name},
                        )
                    except Exception as e:
                        logger.warning("Memory record_entity failed for %s: %s", sender_name, e)

        # Thread/space as entity
        thread_name = raw.get("thread_name", "")
        if thread_name:
            entity_refs.append({"type": "space", "id": f"gchat:{thread_name}"})

        context = {
            "entity_refs": entity_refs,
            "space_name": raw.get("space_name", ""),
            "thread_name": thread_name,
            "participant_count": raw.get("participant_count", 0),
            "message_count": len(raw.get("messages", [])),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
