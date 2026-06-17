import asyncio
import logging
from workbench.providers.llm.base import LLMProvider
from workbench.providers.llm.context import llm_call_context
from workbench.domain import ChangeContext, ExtractedItem, TriageCard, TriageOption

logger = logging.getLogger(__name__)


def _extract_entity_refs(enrichment_context: dict) -> list[tuple]:
    """Extract entity_refs from enrichment context, handling both top-level
    and nested (context.entity_refs) locations.

    FIX 30/31: enrichers return {"calls_made", "time_ms", "context": {...}}.
    entity_refs may be in context.entity_refs or directly on enrichment_context.
    """
    # Try nested context first (standard enricher output format)
    context = enrichment_context.get("context", {})
    if isinstance(context, dict):
        refs = context.get("entity_refs", [])
        if refs:
            return refs

    # Fall back to top-level entity_refs (some enrichers, test scenarios)
    return enrichment_context.get("entity_refs", [])


async def generate_card(
    llm: LLMProvider,
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    *,
    memory=None,
    content_generators: dict | None = None,
    change_context: ChangeContext | None = None,
) -> TriageCard:
    """Generate a triage card with LLM, enriched by memory context.

    Gathers entity knowledge (cap 5), relationships (cap 10), and preference
    facts (cap 20) from memory for any entity_refs found in the enrichment
    context. Dispatches to a registered CardContentGenerator by source_type;
    when none is registered, falls back to llm.generate_triage_card. When
    change_context is provided (re-triage), it is threaded to the generator /
    LLM and the template fallback marks the card "[Updated]" (ADR 0030,0032).
    """
    memory_context = None

    if memory and await memory.is_available():
        entity_refs = _extract_entity_refs(enrichment_context)
        entity_refs = entity_refs[:5]  # cap to avoid excessive queries

        try:
            # Build parallel query lists
            entity_queries = [memory.query_entity(t, i) for t, i in entity_refs]
            relationship_queries = [
                memory.query_relationships(t, i) for t, i in entity_refs
            ]
            preference_query = [memory.query_preferences(item.summary)]

            all_queries = entity_queries + relationship_queries + preference_query
            results = await asyncio.gather(*all_queries, return_exceptions=True)

            n = len(entity_refs)

            # FIX 12: Use raw results (not filtered) for zip alignment.
            # results[:n] corresponds 1:1 with entity_refs.
            raw_entity_results = results[:n]

            entity_facts = {}
            for (etype, eid), entity_result in zip(entity_refs, raw_entity_results):
                if entity_result and not isinstance(entity_result, Exception):
                    # Use .value for enum types to get clean string keys
                    etype_str = etype.value if hasattr(etype, "value") else str(etype)
                    entity_facts[f"{etype_str}:{eid}"] = entity_result.facts

            relationships = []
            for r in results[n : 2 * n]:
                if r and not isinstance(r, Exception):
                    if isinstance(r, list):
                        relationships.extend(r)
                    else:
                        relationships.append(r)

            pref_result = results[-1]
            if isinstance(pref_result, Exception):
                preference_facts = []
            else:
                preference_facts = [f.content for f in (pref_result or [])][:20]

            memory_context = {
                "entity_facts": entity_facts,
                "relationships": [
                    r if isinstance(r, dict) else r.model_dump()
                    for r in relationships[:10]
                ],
                "preference_facts": preference_facts,
            }
        except Exception as e:
            logger.warning("Failed to gather memory context: %s", e)
            memory_context = None

    # Generate card content: dispatch to a registered CardContentGenerator by
    # source_type; otherwise fall back to the default LLM. Template on failure.
    # FIX 30/31: Pass only the context dict, not the full enrichment wrapper.
    context_for_llm = enrichment_context.get("context", enrichment_context)
    generator = (content_generators or {}).get(source_type)
    with llm_call_context(origin="triage", purpose="generate_card", stage="triage"):
        if generator is not None:
            try:
                envelope = await generator.generate(
                    item=item,
                    llm=llm,
                    enrichment_context=context_for_llm,
                    memory_context=memory_context,
                    change_context=change_context,
                )
                card = TriageCard(card_content=envelope)
            except Exception as e:
                logger.warning("Content generator failed, using template: %s", e)
                card = _template_card(
                    item, enrichment_context, source_type, change_context
                )
        else:
            try:
                card = await llm.generate_triage_card(
                    item,
                    context_for_llm,
                    source_type,
                    memory_context=memory_context,
                    change_context=change_context,
                )
            except Exception as e:
                logger.warning("LLM card generation failed, using template: %s", e)
                card = _template_card(
                    item, enrichment_context, source_type, change_context
                )

    # FIX 10: Validate any suggested options
    if memory_context and memory_context.get("preference_facts"):
        for opt in card.options:
            if opt.suggested and not opt.suggestion_reason:
                opt.suggested = False  # Remove invalid suggestions

    # Always append "Other" option for free-text responses
    card.options.append(
        TriageOption(
            label="Other -- tell me what you'd like to do",
            action="other",
        )
    )

    # Surface source identity into card_content for the UI's source-type badge
    # and "open in source" link. Done centrally here so every generation path
    # (registered generator, default LLM, template fallback) gets it uniformly.
    # source_type is backfilled (setdefault) in case a path omitted it; the ref
    # and URL are adapter-populated and only set when present.
    card.card_content.setdefault("source_type", source_type)
    if item.raw_item.source_ref:
        card.card_content["source_ref"] = item.raw_item.source_ref
    if item.raw_item.source_url:
        card.card_content["source_url"] = item.raw_item.source_url

    return card


def _template_card(
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    change_context: ChangeContext | None = None,
) -> TriageCard:
    """Fallback template card when LLM/generator generation fails."""
    card_content = {
        "summary": item.summary,
        "source_type": source_type,
        "enrichment": enrichment_context,
    }
    if change_context is not None:
        card_content["summary"] = f"[Updated] {item.summary}"
        card_content["change"] = change_context.model_dump()
        options = [
            TriageOption(
                label="Bump to P1", action="add_todo", details={"priority": "P1"}
            ),
            TriageOption(label="Keep current priority", action="skip"),
            TriageOption(label="Acknowledge change", action="skip"),
        ]
    else:
        options = [
            TriageOption(
                label="Add todo P1", action="add_todo", details={"priority": "P1"}
            ),
            TriageOption(
                label="Add todo P2", action="add_todo", details={"priority": "P2"}
            ),
            TriageOption(label="Skip", action="skip"),
            TriageOption(
                label=f"Never surface {source_type} like this", action="mute_pattern"
            ),
        ]
    return TriageCard(card_content=card_content, options=options)


def format_card_for_chat(card: TriageCard, position: int = 1, total: int = 1) -> str:
    body = card.card_content.get(
        "card_body", card.card_content.get("summary", "Unknown item")
    )
    source = card.card_content.get("source_type", "unknown")

    lines = []
    if total > 1:
        lines.append(f"*{total} items to triage. Here's #{position} of {total}:*")

    lines.append(f"*[{source}]* {body}")

    enrichment = card.card_content.get("enrichment", {})
    ctx = enrichment.get("context", {}) if isinstance(enrichment, dict) else {}
    if ctx:
        parts = []
        if "author" in ctx:
            parts.append(f"By {ctx['author']}")
        if "files_changed" in ctx:
            parts.append(f"{ctx['files_changed']} files")
        if "review_status" in ctx:
            parts.append(f"review: {ctx['review_status'].replace('_', ' ')}")
        if "labels" in ctx:
            parts.append(ctx["labels"])
        if parts:
            lines.append(f"_{' . '.join(parts)}_")
        handled = {"author", "files_changed", "review_status", "labels", "entity_refs"}
        extra = {k: v for k, v in ctx.items() if k not in handled}
        if extra:
            lines.append(f"_{', '.join(f'{k}: {v}' for k, v in extra.items())}_")

    lines.append("")

    for i, opt in enumerate(card.options, 1):
        suggested_hint = ""
        if opt.suggested and opt.suggestion_reason:
            suggested_hint = f" _(suggested: {opt.suggestion_reason})_"
        lines.append(f"{i}. {opt.label}{suggested_hint}")

    lines.append("")
    lines.append("_Or just reply with what you'd like to do._")

    return "\n".join(lines)
