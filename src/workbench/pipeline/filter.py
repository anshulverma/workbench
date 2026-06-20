import asyncio
import logging
import uuid

from workbench.providers.llm.base import LLMProvider
from workbench.providers.llm.context import llm_call_context
from workbench.providers.memory.base import MemoryLayer
from workbench.storage.base import FilterRuleStore
from workbench.domain import ExtractedItem, Fact, FilterRule

logger = logging.getLogger(__name__)


def decide_from_score(
    relevance: int,
    confidence: int,
    *,
    include_threshold: int = 70,
    drop_threshold: int = 30,
    confidence_threshold: int = 70,
) -> str:
    """Map a (relevance, confidence) score to an action.

    Pure threshold logic, shared by the per-item ``score_and_decide`` path and
    the batched path in the engine (which supplies a precomputed score). The
    thresholds are owned here; callers thread their configured values in. See
    ADR 0048 / spec 3.2.
    """
    if relevance >= include_threshold and confidence >= confidence_threshold:
        return "auto_include"
    elif relevance < drop_threshold and confidence >= confidence_threshold:
        return "auto_drop"
    else:
        return "triage"


async def gather_facts_and_rules(
    memory: MemoryLayer,
    filter_rules: FilterRuleStore,
    item: ExtractedItem,
) -> tuple[list[Fact], list[FilterRule]]:
    """Gather preference/entity/relationship facts + filter rules for one item.

    Extracted so the batched path can collect context for many items
    concurrently before a single ``score_relevance_many`` call.
    """
    preference_facts, entity, relationships = await asyncio.gather(
        memory.query_preferences(item.summary),
        memory.query_entity(item.raw_item.source_type, item.raw_item.id),
        memory.query_relationships(item.raw_item.source_type, item.raw_item.id),
    )

    all_facts = list(preference_facts)

    if entity:
        facts_str = ", ".join(f"{k}: {v}" for k, v in entity.facts.items())
        all_facts.append(
            Fact(
                content=f"{entity.entity_type} {entity.entity_id}: {facts_str}",
                source="entity",
            )
        )

    for rel in relationships:
        all_facts.append(
            Fact(
                content=f"{rel.from_entity} {rel.relation} {rel.to_entity}",
                source="relationship",
            )
        )

    rules = await filter_rules.get_rules()
    source_rules = await filter_rules.get_source_rules(item.raw_item.source_type)
    all_rules = rules + [r for r in source_rules if r not in rules]
    return all_facts, all_rules


async def score_and_decide(
    llm: LLMProvider,
    memory: MemoryLayer,
    filter_rules: FilterRuleStore,
    item: ExtractedItem,
    include_threshold: int = 70,
    drop_threshold: int = 30,
    confidence_threshold: int = 70,
) -> tuple[str, int, int, str]:
    """Returns (action, relevance, confidence, correlation_id).

    The scored child is minted by the caller AFTER this call (allocate_child), so
    the consumed item path is not known here. Stamp a correlation_id (ADR 0064)
    and return it so the caller can record_by_correlation once the child exists.
    """
    all_facts, all_rules = await gather_facts_and_rules(memory, filter_rules, item)

    correlation_id = str(uuid.uuid4())
    with llm_call_context(
        origin="filter",
        purpose="score_relevance",
        stage="filter",
        correlation_id=correlation_id,
    ):
        relevance, confidence = await llm.score_relevance(item, all_facts, all_rules)

    action = decide_from_score(
        relevance,
        confidence,
        include_threshold=include_threshold,
        drop_threshold=drop_threshold,
        confidence_threshold=confidence_threshold,
    )
    return action, relevance, confidence, correlation_id
