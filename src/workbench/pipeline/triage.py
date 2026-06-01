from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, TriageCard

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
    ctx = enrichment.get("context", {}) if enrichment else {}
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
            lines.append(f"_{' · '.join(parts)}_")
        # Render any remaining keys not handled above
        handled = {"author", "files_changed", "review_status", "labels"}
        extra = {k: v for k, v in ctx.items() if k not in handled}
        if extra:
            lines.append(f"_{', '.join(f'{k}: {v}' for k, v in extra.items())}_")

    lines.append("")
    lines.append("*What do you want to do?*")
    for i, opt in enumerate(card.options, 1):
        lines.append(f"{i}. {opt.label}")
    return "\n".join(lines)
