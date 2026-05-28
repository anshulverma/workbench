from workbench.providers.llm.base import LLMProvider
from workbench.memory.base import MemoryLayer
from workbench.storage.base import FilterRuleStore
from workbench.models import ExtractedItem

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
    preference_facts = await memory.query_preferences(item.summary)
    rules = await filter_rules.get_rules()
    source_rules = await filter_rules.get_source_rules(item.raw_item.source_type)
    all_rules = rules + [r for r in source_rules if r not in rules]

    relevance, confidence = await llm.score_relevance(item, preference_facts, all_rules)

    if relevance >= include_threshold and confidence >= confidence_threshold:
        return "auto_include", relevance, confidence
    elif relevance < drop_threshold and confidence >= confidence_threshold:
        return "auto_drop", relevance, confidence
    else:
        return "triage", relevance, confidence
