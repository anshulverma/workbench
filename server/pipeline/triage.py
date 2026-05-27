from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem, TriageCard

async def generate_card(llm: LLMProvider, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
    return await llm.generate_triage_card(item, enrichment_context, source_type)

def format_card_for_chat(card: TriageCard, position: int = 1, total: int = 1) -> str:
    """Format a triage card as text for Google Chat."""
    summary = card.card_content.get("summary", "Unknown item")
    source = card.card_content.get("source_type", "unknown")
    lines = []
    if total > 1:
        lines.append(f"*{total} items to triage. Here's #{position} of {total}:*")
    lines.append(f"*[{source}]* {summary}")
    enrichment = card.card_content.get("enrichment", {})
    if enrichment:
        ctx = enrichment.get("context", {})
        if ctx:
            lines.append(f"_Context: {', '.join(str(v) for v in ctx.values())}_")
    lines.append("")
    lines.append("*What do you want to do?*")
    for i, opt in enumerate(card.options, 1):
        lines.append(f"{i}. {opt.label}")
    return "\n".join(lines)
