from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from memory.extraction import FACT_INGESTION_PROMPT, format_triage_narrative
from memory.models import Fact

logger = logging.getLogger(__name__)

ACTION_TO_EDGE = {
    "add_todo": "prefers",
    "skip": "avoids",
    "mute_pattern": "avoids",
}


class GraphitiMemoryLayer:
    def __init__(self, graphiti):
        self.graphiti = graphiti

    async def record_triage(self, card: dict, response: dict) -> None:
        content = card.get("card_content", {})
        summary = content.get("summary", "")
        source_type = content.get("source_type", "unknown")
        card_id = card.get("id", "unknown")
        options = card.get("options", [])
        choice = response.get("choice", 0)

        chosen_option = options[choice - 1] if 1 <= choice <= len(options) else {}
        action = chosen_option.get("action", "unknown")
        details = chosen_option.get("details", {})

        # Layer 1: Structured writes (deterministic)
        await self._create_preference_edge(summary, source_type, action, details)

        # Layer 2: Episode fact ingestion (LLM)
        narrative = format_triage_narrative(card, response)
        try:
            from graphiti_core.nodes import EpisodeType
            await self.graphiti.add_episode(
                name=f"triage-{card_id}",
                episode_body=narrative,
                source_description="workbench triage interaction",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                custom_extraction_instructions=FACT_INGESTION_PROMPT,
            )
        except Exception as e:
            logger.error("Failed to ingest triage episode: %s", e, exc_info=True)
            raise

    async def _create_preference_edge(
        self, summary: str, source_type: str, action: str, details: dict
    ) -> None:
        from graphiti_core.nodes import EntityNode
        from graphiti_core.edges import EntityEdge

        edge_name = ACTION_TO_EDGE.get(action, "triaged")
        attributes = {"action": action, "source_type": source_type}
        if action == "add_todo":
            attributes["priority"] = details.get("priority", "P2")
        if action == "mute_pattern":
            attributes["permanent"] = True

        user_node = EntityNode(
            uuid=str(uuid4()),
            name="user",
            labels=["User"],
            group_id="workbench",
        )
        pattern_node = EntityNode(
            uuid=str(uuid4()),
            name=summary,
            labels=["Pattern"],
            attributes={"source_type": source_type},
            group_id="workbench",
        )
        edge = EntityEdge(
            uuid=str(uuid4()),
            name=edge_name,
            fact=f"User {edge_name} items like: {summary}",
            source_node_uuid=user_node.uuid,
            target_node_uuid=pattern_node.uuid,
            created_at=datetime.now(timezone.utc),
            attributes=attributes,
            group_id="workbench",
        )

        try:
            await self.graphiti.add_triplet(user_node, edge, pattern_node)
        except Exception as e:
            logger.warning("Failed to create structured preference edge: %s", e)

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            edges = await self.graphiti.search(query=context, num_results=10)
            return [
                Fact(
                    content=edge.fact,
                    source="graphiti",
                    timestamp=edge.valid_at or datetime.now(timezone.utc),
                )
                for edge in edges
                if edge.fact
            ]
        except Exception as e:
            logger.error("Failed to query preferences: %s", e, exc_info=True)
            return []
