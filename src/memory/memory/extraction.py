from datetime import datetime, timezone

FACT_INGESTION_PROMPT = """You are extracting user preference patterns from triage interactions.
Focus on:
- What types of items the user consistently prioritizes or ignores
- Source types, topics, people, or patterns that predict user interest
- Priority signals the user responds to (blocking reviewers, P0 incidents, etc.)

Extract facts in the form: "User [always/never/usually] [action] [item pattern] [when condition]"
Examples:
- "User always prioritizes diffs where reviewers are blocked"
- "User never engages with automated CI notifications"
- "User usually skips emails about infrastructure announcements"
"""


def format_triage_narrative(card: dict, response: dict) -> str:
    content = card.get("card_content", {})
    summary = content.get("summary", "Unknown item")
    source_type = content.get("source_type", "unknown")
    relevance = card.get("relevance_score", 0)
    options = card.get("options", [])
    choice = response.get("choice", 0)

    options_text = "\n".join(
        f"  {i}. {opt.get('label', '?')}" for i, opt in enumerate(options, 1)
    )

    chosen_label = ""
    if 1 <= choice <= len(options):
        chosen_label = options[choice - 1].get("label", "?")

    now = datetime.now(timezone.utc).isoformat()

    return f"""Triage interaction at {now}:
Source type: {source_type}
Item summary: "{summary}"
Relevance score: {relevance}
Options presented:
{options_text}
User chose: {choice}. {chosen_label}"""


DECISION_EXTRACTION_PROMPT = """You are extracting patterns about pipeline filtering decisions.
Focus on:
- What types of items the pipeline consistently includes or drops
- Source types, topics, or patterns that predict inclusion/exclusion
- Threshold behaviors (items near the relevance cutoff)

Extract facts in the form: "Pipeline [always/never/usually] [includes/drops] [item pattern] [when condition]"
"""


def format_decision_narrative(
    item_summary: str,
    decision: str,
    reason: str,
    source_type: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()

    return f"""Pipeline decision at {now}:
Source type: {source_type}
Item summary: "{item_summary}"
Decision: {decision}
Reason: {reason}"""
