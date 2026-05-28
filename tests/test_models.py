# tests/test_models.py
import pytest
from workbench.models import (
    Item, ItemStatus, ItemCategory, ItemOrigin, Priority,
    RawItem, ExtractedItem, TriageCard, TriageOption,
    FilterRule, InteractionEntry, PipelineJob, JobStatus, JobTrigger,
)

def test_item_defaults():
    item = Item(
        source_type="diff",
        source_id="D12345",
        summary="Review auth middleware",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P1,
    )
    assert item.status == ItemStatus.ACTIVE
    assert item.id  # auto-generated
    assert item.created_at

def test_raw_item():
    raw = RawItem(id="D12345_123", source_type="diff", source_label="D12345", raw_text="content")
    assert raw.source_type == "diff"

def test_extracted_item():
    raw = RawItem(id="1", source_type="email", source_label="test", raw_text="hi")
    extracted = ExtractedItem(summary="Test", category=ItemCategory.ACTION_ITEM, source_context="ctx", raw_item=raw)
    assert extracted.category == ItemCategory.ACTION_ITEM

def test_triage_card_with_options():
    card = TriageCard(
        card_content={"summary": "Review D12345"},
        options=[
            TriageOption(label="Add review todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    assert len(card.options) == 2
    assert card.responded_at is None

def test_pipeline_job_defaults():
    job = PipelineJob(trigger=JobTrigger.MANUAL)
    assert job.status == JobStatus.PENDING
    assert job.items_extracted == 0

def test_filter_rule():
    rule = FilterRule(pattern="CI bot comments on diffs", action="drop")
    assert rule.source_type is None
    assert rule.action == "drop"
