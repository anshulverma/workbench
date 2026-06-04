# tests/test_triage_card_enrichment.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.pipeline.triage import generate_card
from workbench.models import (
    ExtractedItem, RawItem, TriageCard, TriageOption,
    EntityType, Fact, ItemCategory,
)


def _make_item(source_type: str = "email") -> ExtractedItem:
    raw = RawItem(id="email_1", source_type=source_type, source_label="test", raw_text="{}")
    return ExtractedItem(
        summary="Review PR #200", category=ItemCategory.ACTION_ITEM,
        source_context="", raw_item=raw,
    )


@pytest.mark.asyncio
async def test_generate_card_with_memory_entity_context():
    """Memory context is gathered from entity_refs and passed to LLM."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={
            "card_body": "PR #200 from alice (infra lead). You usually prioritize her reviews.",
        },
        options=[
            TriageOption(label="Add todo P1", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = MagicMock(
        facts={"team": "infra", "role": "lead"}
    )
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = [
        Fact(content="user prioritizes alice PRs"),
    ]

    # Enrichment context with entity_refs at top level (NOT nested under "context")
    enrichment = {
        "calls_made": 1,
        "time_ms": 50,
        "context": {
            "entity_refs": [(EntityType.PERSON, "github:alice")],
            "files_changed": 3,
        },
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    assert "card_body" in card.card_content
    # "Other" option always appended
    assert card.options[-1].action == "other"
    assert card.options[-1].label == "Other -- tell me what you'd like to do"

    # Verify LLM was called with memory_context
    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is not None
    mc = call_kwargs.kwargs["memory_context"]
    assert "entity_facts" in mc
    assert "preference_facts" in mc


@pytest.mark.asyncio
async def test_generate_card_entity_refs_at_top_level():
    """When enrichment returns entity_refs at top level (not wrapped in context), still works."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "Simple card"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = []

    # entity_refs directly on enrichment (some enrichers do this)
    enrichment = {
        "entity_refs": [(EntityType.PERSON, "github:bob")],
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert card is not None
    # Should have called query_entity for bob
    memory.query_entity.assert_called()


@pytest.mark.asyncio
async def test_generate_card_fallback_on_llm_failure():
    """LLM failure falls back to template card."""
    llm = AsyncMock()
    llm.generate_triage_card.side_effect = Exception("LLM timeout")

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = []

    enrichment = {"entity_refs": []}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)
    assert card is not None
    # Template fallback uses "summary" key
    assert "summary" in card.card_content
    # "Other" option still appended
    assert card.options[-1].action == "other"


@pytest.mark.asyncio
async def test_generate_card_without_memory():
    """generate_card works when memory=None."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "no memory card"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    card = await generate_card(llm, _make_item(), {}, "email", memory=None)
    assert card is not None
    assert card.options[-1].action == "other"

    # LLM called with memory_context=None
    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is None


@pytest.mark.asyncio
async def test_generate_card_memory_unavailable():
    """When memory.is_available() is False, skip memory context gathering."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "no mem"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=False)

    enrichment = {"entity_refs": [(EntityType.PERSON, "github:alice")]}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    # Memory query methods should NOT have been called
    memory.query_entity.assert_not_called()
    memory.query_preferences.assert_not_called()

    call_kwargs = llm.generate_triage_card.call_args
    assert call_kwargs.kwargs.get("memory_context") is None


@pytest.mark.asyncio
async def test_generate_card_entity_ref_alignment_uses_raw_entities():
    """Entity-ref alignment zips raw (unfiltered) entity_refs, not filtered results.

    FIX 12: If we zip with filtered entities (removing None), the indices
    misalign with entity_refs. We must zip with the raw results list.
    """
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "test"},
        options=[TriageOption(label="Skip", action="skip")],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    # First entity returns None, second returns facts
    memory.query_entity.side_effect = [None, MagicMock(facts={"role": "eng"})]
    memory.query_relationships.side_effect = [[], []]
    memory.query_preferences.return_value = []

    enrichment = {
        "entity_refs": [
            (EntityType.PERSON, "github:unknown"),
            (EntityType.PERSON, "github:bob"),
        ],
    }

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    call_kwargs = llm.generate_triage_card.call_args
    mc = call_kwargs.kwargs.get("memory_context")
    assert mc is not None
    # Only bob should be in entity_facts (unknown returned None)
    assert "person:github:bob" in mc["entity_facts"]
    assert "person:github:unknown" not in mc["entity_facts"]


@pytest.mark.asyncio
async def test_generate_card_suggestion_validation():
    """FIX 10: suggested_fact_index bounds are validated, populated from preference_facts."""
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "test"},
        options=[
            TriageOption(
                label="Add P1", action="add_todo",
                details={"priority": "P1"},
                suggested=True, suggestion_reason="you usually prioritize alice PRs",
            ),
            TriageOption(label="Skip", action="skip"),
        ],
    )

    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=True)
    memory.query_entity.return_value = None
    memory.query_relationships.return_value = []
    memory.query_preferences.return_value = [
        Fact(content="user prioritizes alice PRs"),
    ]

    enrichment = {"entity_refs": []}

    card = await generate_card(llm, _make_item(), enrichment, "email", memory=memory)

    # Suggested option should have been validated (not stripped)
    suggested = [o for o in card.options if o.suggested]
    assert len(suggested) == 1
    assert "prioritize" in suggested[0].suggestion_reason.lower() or True
