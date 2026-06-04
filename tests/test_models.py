# tests/test_models.py
import pytest
from workbench.models import (
    Item, ItemStatus, ItemCategory, ItemOrigin, Priority,
    RawItem, ExtractedItem, TriageCard, TriageOption, TriageResponse,
    FilterRule, InteractionEntry, PipelineJob, JobStatus, JobTrigger,
    IngestionQueueEntry, QueueEntryStatus,
    EntityType, ActionCategory,
    InterpretedResponse, SystemAction, UserTodo, TriageResponseResult,
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

def test_interaction_entry_choice_index_default():
    entry = InteractionEntry(source_type="diff", item_summary="Review D123")
    assert entry.choice_index is None

def test_interaction_entry_choice_index_set():
    entry = InteractionEntry(source_type="diff", item_summary="Review D123", choice_index=2)
    assert entry.choice_index == 2


def test_entity_type_enum():
    assert EntityType.PERSON == "person"
    assert EntityType.REPO == "repo"
    assert EntityType.TEAM == "team"
    assert EntityType.SPACE == "space"
    assert EntityType.GROUP == "group"


def test_action_category_enum():
    assert ActionCategory.DELEGATION == "delegation"
    assert ActionCategory.COMMUNICATION == "communication"
    assert ActionCategory.SCHEDULING == "scheduling"
    assert ActionCategory.REVIEW == "review"
    assert ActionCategory.CREATION == "creation"
    assert ActionCategory.UPDATE == "update"
    assert ActionCategory.DECISION == "decision"
    assert ActionCategory.INVESTIGATION == "investigation"


def test_triage_option_suggested_fields():
    opt = TriageOption(label="Add todo P1", action="add_todo")
    assert opt.suggested is False
    assert opt.suggestion_reason is None
    opt2 = TriageOption(
        label="Skip", action="skip",
        suggested=True, suggestion_reason="you usually skip bot PRs",
    )
    assert opt2.suggested is True
    assert opt2.suggestion_reason == "you usually skip bot PRs"


def test_triage_card_deferred_until():
    card = TriageCard()
    assert card.deferred_until is None


def test_item_action_fields():
    item = Item(
        source_type="email", source_id="e1",
        summary="test", category="action_item",
        origin="manual", priority="P2",
    )
    assert item.parent_item_id is None
    assert item.action_source is None
    assert item.action_category is None
    assert item.snoozed_until is None
    assert item.completed_at is None
    item2 = Item(
        source_type="email", source_id="e2",
        summary="Assign to bob",
        category="action_item",
        origin="triaged", priority="P2",
        parent_item_id="parent-123",
        action_source="triage_response",
        action_category="delegation",
    )
    assert item2.parent_item_id == "parent-123"
    assert item2.action_source == "triage_response"
    assert item2.action_category == "delegation"


def test_triage_response_choice_optional():
    resp = TriageResponse(card_id="c1", choice=2)
    assert resp.choice == 2
    resp2 = TriageResponse(card_id="c1", raw_text="add as P3")
    assert resp2.choice is None
    assert resp2.raw_text == "add as P3"


def test_interaction_entry_interpreted_fields():
    entry = InteractionEntry(
        source_type="email", item_summary="test",
    )
    assert entry.type is None
    assert entry.interpreted is None
    assert entry.confirmed is None


def test_interpreted_response():
    resp = InterpretedResponse(
        system_actions=[SystemAction(action="add_todo", details={"priority": "P3"})],
        user_todos=[UserTodo(summary="Assign to bob", action_category="delegation")],
        explanation="Adding as P3 todo.",
    )
    assert len(resp.system_actions) == 1
    assert resp.system_actions[0].action == "add_todo"
    assert len(resp.user_todos) == 1
    assert resp.user_todos[0].action_category == "delegation"


def test_triage_response_result():
    result = TriageResponseResult(
        status="recorded",
        action="add_todo",
        system_actions_executed=["add_todo"],
        user_todos_created=["todo-1"],
        explanation="Added as P3 todo.",
    )
    assert result.status == "recorded"
    assert result.action == "add_todo"
