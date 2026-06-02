import asyncio
import logging

from workbench.providers.llm.base import LLMProvider
from workbench.memory.base import MemoryLayer
from workbench.storage.base import FilterRuleStore
from workbench.models import ExtractedItem, Fact

logger = logging.getLogger(__name__)


async def score_and_decide(
    llm: LLMProvider,
    memory: MemoryLayer,
    filter_rules: FilterRuleStore,
    item: ExtractedItem,
    include_threshold: int = 70,
    drop_threshold: int = 30,
    confidence_threshold: int = 70,
) -> tuple[str, int, int]:
    """Returns (action, relevance, confidence). Action is 'auto_include', 'auto_drop', or 'triage'."""
    preference_facts, entity, relationships = await asyncio.gather(
        memory.query_preferences(item.summary),
        memory.query_entity(item.raw_item.source_type, item.raw_item.id),
        memory.query_relationships(item.raw_item.source_type, item.raw_item.id),
    )

    all_facts = list(preference_facts)

    if entity:
        facts_str = ", ".join(f"{k}: {v}" for k, v in entity.facts.items())
        all_facts.append(Fact(
            content=f"{entity.entity_type} {entity.entity_id}: {facts_str}",
            source="entity",
        ))

    for rel in relationships:
        all_facts.append(Fact(
            content=f"{rel.from_entity} {rel.relation} {rel.to_entity}",
            source="relationship",
        ))

    rules = await filter_rules.get_rules()
    source_rules = await filter_rules.get_source_rules(item.raw_item.source_type)
    all_rules = rules + [r for r in source_rules if r not in rules]

    relevance, confidence = await llm.score_relevance(item, all_facts, all_rules)

    if relevance >= include_threshold and confidence >= confidence_threshold:
        return "auto_include", relevance, confidence
    elif relevance < drop_threshold and confidence >= confidence_threshold:
        return "auto_drop", relevance, confidence
    else:
        return "triage", relevance, confidence
