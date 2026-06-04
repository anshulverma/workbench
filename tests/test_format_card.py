import pytest
from workbench.pipeline.triage import format_card_for_chat
from workbench.models import TriageCard, TriageOption


def test_format_uses_card_body_when_present():
    card = TriageCard(
        card_content={
            "card_body": "PR #200 from alice (infra lead). You usually prioritize her reviews.",
            "summary": "Review PR #200",
            "source_type": "github",
        },
        options=[
            TriageOption(label="Add P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
            TriageOption(label="Other -- tell me what you'd like to do", action="other"),
        ],
    )
    text = format_card_for_chat(card)
    assert "alice (infra lead)" in text
    assert "1. Add P1" in text
    assert "2. Skip" in text
    assert "3. Other" in text
    assert "reply with what you'd like to do" in text


def test_format_falls_back_to_summary():
    card = TriageCard(
        card_content={"summary": "Fix auth flow", "source_type": "github"},
        options=[
            TriageOption(label="Add P2", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "Fix auth flow" in text


def test_format_shows_suggested_option():
    card = TriageCard(
        card_content={"card_body": "PR from alice", "summary": "PR review"},
        options=[
            TriageOption(
                label="Add P1", action="add_todo",
                details={"priority": "P1"},
                suggested=True,
                suggestion_reason="you usually prioritize alice PRs",
            ),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card)
    assert "suggested" in text.lower()
    assert "you usually prioritize alice PRs" in text


def test_format_shows_enrichment_context():
    card = TriageCard(
        card_content={
            "card_body": "PR #200",
            "summary": "PR #200",
            "source_type": "github",
            "enrichment": {
                "context": {
                    "author": "alice",
                    "files_changed": 5,
                    "review_status": "changes_requested",
                },
            },
        },
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "alice" in text
    assert "5 files" in text


def test_format_with_position_and_total():
    card = TriageCard(
        card_content={"card_body": "Item A", "summary": "Item A", "source_type": "email"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card, position=2, total=5)
    assert "5 items to triage" in text
    assert "#2 of 5" in text


def test_format_no_position_for_single_card():
    card = TriageCard(
        card_content={"card_body": "Solo card", "summary": "Solo card"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card, position=1, total=1)
    assert "items to triage" not in text


def test_format_free_text_hint():
    card = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    text = format_card_for_chat(card)
    assert "reply with what you'd like to do" in text
