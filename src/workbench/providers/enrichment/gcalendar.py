from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from workbench.models import ExtractedItem, EnrichmentBudget
from workbench.providers.enrichment.base import ContextEnricher

logger = logging.getLogger(__name__)


class GCalendarEnricher(ContextEnricher):
    class ProviderConfig(BaseModel):
        pass

    def __init__(self, config: ProviderConfig = None, connection=None):
        self._config = config
        self._connection = connection

    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None
    ) -> dict:
        if item.raw_item.source_type != "calendar":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()

        try:
            raw = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"calls_made": 0, "time_ms": elapsed_ms, "context": {}}

        entity_refs: list[dict[str, str]] = []
        calls_made = 0

        # Organizer entity
        organizer = raw.get("organizer", "")
        if organizer:
            entity_refs.append({"type": "person", "id": f"gcal:{organizer}"})

        # Attendee entities
        for attendee in raw.get("attendees", []):
            email = attendee.get("email", "")
            if email:
                entity_refs.append({"type": "person", "id": f"gcal:{email}"})

        # Record organizer in memory
        if memory and organizer:
            try:
                await memory.record_entity(
                    "person",
                    f"gcal:{organizer}",
                    {"email": organizer, "name": organizer.split("@")[0]},
                )
            except Exception as e:
                logger.warning("Memory record_entity failed for %s: %s", organizer, e)

        context = {
            "entity_refs": entity_refs,
            "summary": raw.get("summary", ""),
            "organizer": organizer,
            "attendee_count": len(raw.get("attendees", [])),
            "location": raw.get("location", ""),
            "start": raw.get("start", ""),
            "end": raw.get("end", ""),
            "is_recurring": raw.get("is_recurring", False),
        }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
