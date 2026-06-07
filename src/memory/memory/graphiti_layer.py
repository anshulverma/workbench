from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from memory.extraction import (
    DECISION_EXTRACTION_PROMPT,
    FACT_INGESTION_PROMPT,
    format_decision_narrative,
    format_triage_narrative,
)
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

    @staticmethod
    def _is_tombstoned(edge) -> bool:
        # Defensive: Graphiti search normally already excludes invalidated
        # edges. Only treat real datetime values as a tombstone marker so
        # edges that simply lack the attribute (or set it None) still surface.
        for attr in ("invalid_at", "expired_at"):
            value = getattr(edge, attr, None)
            if isinstance(value, datetime):
                return True
        return False

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            edges = await self.graphiti.search(query=context, num_results=10)
            return [
                Fact(
                    id=getattr(edge, "uuid", None),
                    content=edge.fact,
                    source="graphiti",
                    timestamp=edge.valid_at or datetime.now(timezone.utc),
                )
                for edge in edges
                if edge.fact and not self._is_tombstoned(edge)
            ]
        except Exception as e:
            logger.error("Failed to query preferences: %s", e, exc_info=True)
            return []

    async def delete_fact(self, fact_id: str) -> None:
        """Tombstone (invalidate) a fact edge by uuid.

        Per ADR 0019 this is a bi-temporal invalidation, NOT a hard delete:
        we set the edge's invalid_at/expired_at so it stops surfacing in
        search/queries but remains in the graph for audit and is not
        re-synthesized.
        """
        from graphiti_core.edges import EntityEdge

        edge = await EntityEdge.get_by_uuid(self.graphiti.driver, fact_id)
        if edge is None:
            raise KeyError(f"Fact edge not found: {fact_id}")

        now = datetime.now(timezone.utc)
        edge.invalid_at = now
        edge.expired_at = now
        try:
            await edge.save(self.graphiti.driver)
        except Exception as e:
            logger.error("Failed to tombstone fact %s: %s", fact_id, e, exc_info=True)
            raise

    async def update_fact(self, fact_id: str, content: str) -> None:
        """Edit a fact edge's text by uuid.

        Per ADR 0019 this is an authoritative user override. We set the edge's
        fact text and mark it user-asserted (when the attribute is available)
        so re-extraction does not overwrite it.
        """
        from graphiti_core.edges import EntityEdge

        edge = await EntityEdge.get_by_uuid(self.graphiti.driver, fact_id)
        if edge is None:
            raise KeyError(f"Fact edge not found: {fact_id}")

        edge.fact = content
        # Pin as user-asserted so re-extraction won't overwrite, if supported.
        if hasattr(edge, "attributes") and isinstance(edge.attributes, dict):
            edge.attributes["user_asserted"] = True
        try:
            await edge.save(self.graphiti.driver)
        except Exception as e:
            logger.error("Failed to update fact %s: %s", fact_id, e, exc_info=True)
            raise

    async def record_entity(
        self, entity_type: str, entity_id: str, facts: dict, store
    ) -> str | None:
        from graphiti_core.nodes import EntityNode
        from graphiti_core.edges import EntityEdge

        # Step 1: Identity resolution in PG store
        canonical_id = await store.resolve_identity(entity_type, entity_id, facts)

        # Step 2: Graph writes using canonical_id
        source_node = EntityNode(
            uuid=str(uuid4()),
            name=f"{entity_type}:{canonical_id}",
            labels=["Entity"],
            attributes={"entity_type": entity_type},
            group_id="workbench",
        )

        graph_uuid = None
        for key, value in facts.items():
            fact_node = EntityNode(
                uuid=str(uuid4()),
                name=str(value),
                labels=["Fact"],
                attributes={"key": key},
                group_id="workbench",
            )
            edge = EntityEdge(
                uuid=str(uuid4()),
                name=f"has_fact_{key}",
                fact=f"{entity_type}:{canonical_id} has {key} = {value}",
                source_node_uuid=source_node.uuid,
                target_node_uuid=fact_node.uuid,
                created_at=datetime.now(timezone.utc),
                group_id="workbench",
            )
            result = await self.graphiti.add_triplet(source_node, edge, fact_node)
            if result and hasattr(result, "nodes") and result.nodes:
                for node in result.nodes:
                    if hasattr(node, "name") and node.name == source_node.name:
                        graph_uuid = node.uuid
                        break
            if graph_uuid is None:
                graph_uuid = source_node.uuid

        # Step 3: PG write only after graph succeeds -- upsert under canonical_id
        await store.upsert_entity(entity_type, canonical_id, facts)
        if graph_uuid:
            await store.update_graph_uuid(entity_type, canonical_id, graph_uuid)

        return graph_uuid

    async def query_entity(
        self, entity_type: str, entity_id: str, store
    ) -> dict | None:
        return await store.get_entity_resolved(entity_type, entity_id)

    async def record_decision(
        self,
        item_summary: str,
        decision: str,
        reason: str,
        source_type: str,
        store,
    ) -> None:
        from graphiti_core.nodes import EntityNode, EpisodeType
        from graphiti_core.edges import EntityEdge

        # Layer 1: Structured edge
        edge_name = "included" if decision == "auto_include" else "dropped"
        pipeline_node = EntityNode(
            uuid=str(uuid4()),
            name="pipeline",
            labels=["Pipeline"],
            group_id="workbench",
        )
        pattern_node = EntityNode(
            uuid=str(uuid4()),
            name=item_summary,
            labels=["Pattern"],
            attributes={"source_type": source_type},
            group_id="workbench",
        )
        edge = EntityEdge(
            uuid=str(uuid4()),
            name=edge_name,
            fact=f"Pipeline {edge_name} items like: {item_summary} (reason: {reason})",
            source_node_uuid=pipeline_node.uuid,
            target_node_uuid=pattern_node.uuid,
            created_at=datetime.now(timezone.utc),
            attributes={"reason": reason, "source_type": source_type},
            group_id="workbench",
        )

        try:
            await self.graphiti.add_triplet(pipeline_node, edge, pattern_node)
        except Exception as e:
            logger.warning("Failed to create decision edge: %s", e)

        # Layer 2: Episode ingestion via queue
        narrative = format_decision_narrative(
            item_summary, decision, reason, source_type
        )
        try:
            await self.graphiti.add_episode(
                name=f"decision-{uuid4()}",
                episode_body=narrative,
                source_description="workbench pipeline decision",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                custom_extraction_instructions=DECISION_EXTRACTION_PROMPT,
            )
        except Exception as e:
            logger.error("Failed to ingest decision episode: %s", e, exc_info=True)
            raise

    async def query_relationships(
        self, entity_type: str, entity_id: str, store
    ) -> list[dict]:
        entity = await store.get_entity(entity_type, entity_id)
        if not entity or not entity.get("graph_uuid"):
            return []

        graph_uuid = entity["graph_uuid"]
        try:
            records = await self.graphiti.driver.execute_query(
                "MATCH (n:Entity {uuid: $uuid})-[e:RELATES_TO]-(m:Entity) "
                "RETURN n.name AS from_entity, m.name AS to_entity, "
                "e.name AS relation, e.fact AS fact",
                {"uuid": graph_uuid},
            )
            return [
                {
                    "from_entity": r["from_entity"],
                    "to_entity": r["to_entity"],
                    "relation": r["relation"],
                }
                for r in records
            ]
        except Exception as e:
            logger.warning("Failed to query relationships: %s", e)
            return []
