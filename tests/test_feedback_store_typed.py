# tests/test_feedback_store_typed.py
import pytest

from workbench.domain import FeedbackCorrection, FilterTuningTask

pytestmark = pytest.mark.asyncio


async def test_correction_roundtrips_typed_fields(stores):
    c = await stores.feedback.add_correction(
        FeedbackCorrection(
            item_id=1,
            filter_id="5",
            item_summary="fix the thing",
            original_action="drop",
            corrected_action="include",
            from_label="Drop",
            to_label="Keep",
            reason="user override",
        )
    )
    assert c.id is not None
    got = await stores.feedback.get_corrections(item_id=1)
    assert got[0].filter_id == "5"
    assert got[0].item_summary == "fix the thing"
    assert got[0].from_label == "Drop"
    assert got[0].to_label == "Keep"


async def test_task_roundtrips_typed_fields(stores):
    t = await stores.feedback.add_task(
        FilterTuningTask(
            filter_id="5",
            item_id=1,
            item_summary="fix the thing",
            from_outcome="drop",
            to_outcome="include",
            from_label="Drop",
            to_label="Keep",
            filter_prompt="Drop noise",
            proposed_prompt="Drop noise but keep X",
            kind="filter-tuning",
            correction_ids=[1],
            status="open",
        )
    )
    assert t.id is not None and t.rule_id is None
    got = await stores.feedback.get_tasks(status="open")
    row = next(x for x in got if x.id == t.id)
    assert row.filter_id == "5"
    assert row.item_summary == "fix the thing"
    assert row.from_outcome == "drop" and row.to_outcome == "include"
    assert row.proposed_prompt == "Drop noise but keep X"
    assert row.correction_ids == [1]


async def test_update_task_sets_resolved_at(stores):
    t = await stores.feedback.add_task(
        FilterTuningTask(
            filter_id="5",
            item_id=1,
            proposed_prompt="p",
            correction_ids=[],
            status="open",
        )
    )
    updated = await stores.feedback.update_task(t.id, "applied")
    assert updated.status == "applied" and updated.resolved_at is not None
