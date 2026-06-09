from __future__ import annotations

from workbench.domain import ChangeContext, TriageCard
from workbench.providers.change_detector.base import ChangeResult


def build_change_context(
    result: ChangeResult,
    old_raw: dict,
    new_raw: dict,
    previous_card: TriageCard | None,
) -> ChangeContext:
    """Build a ChangeContext from a ChangeResult plus old/new raw data and the
    previous triage card (for prior action/priority continuity)."""
    changed_fields: dict[str, dict[str, str]] = {}
    for field in result.changed_fields:
        changed_fields[field] = {
            "old": str(old_raw.get(field, "")),
            "new": str(new_raw.get(field, "")),
        }

    prev_action = None
    prev_priority = None
    if previous_card and previous_card.status == "responded":
        prev_action = previous_card.response
        if previous_card.card_content:
            prev_priority = previous_card.card_content.get("priority")

    return ChangeContext(
        change_type=result.change_type,
        changed_fields=changed_fields,
        change_summary=result.reason,
        previous_triage_action=prev_action,
        previous_priority=prev_priority,
    )
