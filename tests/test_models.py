# tests/test_models.py
import pytest
from workbench.models import (
    Item, ItemStatus, ItemCategory, ItemOrigin, Priority,
    RawItem, ExtractedItem, TriageCard, TriageOption,
    FilterRule, InteractionEntry, PipelineJob, JobStatus, JobTrigger,
    IngestionQueueEntry, QueueEntryStatus,
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

def test_item_status_includes_pending_triage():
    assert ItemStatus.PENDING_TRIAGE.value == "pending_triage"

def test_job_status_includes_queued():
    assert JobStatus.QUEUED.value == "queued"

def test_item_category_includes_plan_seed():
    assert ItemCategory.PLAN_SEED.value == "plan_seed"

def test_raw_item_has_urgency_signals():
    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="content")
    assert raw.urgency_signals == {}
    raw2 = RawItem(id="2", source_type="diff", source_label="D456", raw_text="content",
                   urgency_signals={"blocking_reviewer": True})
    assert raw2.urgency_signals["blocking_reviewer"] is True

def test_ingestion_queue_entry_defaults():
    entry = IngestionQueueEntry(raw_content="test", source_type="manual", job_id="j1")
    assert entry.status == QueueEntryStatus.QUEUED
    assert entry.attempt == 0
    assert entry.urgency_score == 50

def test_triage_card_queue_fields():
    card = TriageCard()
    assert card.status == "queued"
    assert card.relevance_score == 50
    assert card.bot_message_id is None
    assert card.expires_at is None
