from workbench.domain import ChangeContext, TriageCard
from workbench.providers.change_detector.base import ChangeResult
from workbench.pipeline.change_context import build_change_context


def _result(fields=None):
    return ChangeResult(
        is_material=True,
        change_type="status_changed",
        changed_fields=fields or ["status"],
        reason="status changed",
    )


def test_build_no_previous_card():
    ctx = build_change_context(
        _result(), {"status": "needs_review"}, {"status": "accepted"}, None
    )
    assert isinstance(ctx, ChangeContext)
    assert ctx.change_type == "status_changed"
    assert ctx.changed_fields["status"] == {"old": "needs_review", "new": "accepted"}
    assert ctx.change_summary == "status changed"
    assert ctx.previous_triage_action is None
    assert ctx.previous_priority is None


def test_build_with_responded_card_copies_action_and_priority():
    card = TriageCard(
        card_content={"priority": "P2"}, status="responded", response="defer"
    )
    ctx = build_change_context(_result(), {"status": "a"}, {"status": "b"}, card)
    assert ctx.previous_triage_action == "defer"
    assert ctx.previous_priority == "P2"


def test_build_with_non_responded_card_leaves_previous_none():
    card = TriageCard(card_content={"priority": "P2"}, status="sent", response=None)
    ctx = build_change_context(_result(), {"status": "a"}, {"status": "b"}, card)
    assert ctx.previous_triage_action is None
    assert ctx.previous_priority is None


def test_build_missing_field_in_raw_uses_empty_string():
    ctx = build_change_context(_result(["ci"]), {}, {}, None)
    assert ctx.changed_fields["ci"] == {"old": "", "new": ""}
