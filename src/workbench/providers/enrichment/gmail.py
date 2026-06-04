from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GmailEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "email":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[dict[str, str]] = []
        calls_made = 0

        sender = raw.get("sender", "")
        if sender:
            entity_refs.append({"type": "person", "id": f"email:{sender}"})
            if memory:
                try:
                    await memory.record_entity(
                        "person",
                        f"email:{sender}",
                        {"email": sender, "name": sender.split("@")[0]},
                    )
                except Exception as e:
                    logger.warning("Memory record_entity failed for %s: %s", sender, e)

        for recipient in raw.get("recipients_to", []) + raw.get("recipients_cc", []):
            if recipient:
                entity_refs.append({"type": "person", "id": f"email:{recipient}"})

        context = {
            "entity_refs": entity_refs,
            "subject": raw.get("subject", ""),
            "sender": sender,
            "thread_id": raw.get("thread_id", ""),
            "attachments": raw.get("attachments", []),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
