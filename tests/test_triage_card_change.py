import pytest
from unittest.mock import AsyncMock
from workbench.domain import (
    ExtractedItem,
    RawItem,
    ItemCategory,
    TriageCard,
    ChangeContext,
)
from workbench.pipeline.content_generator import CardContentGenerator
from workbench.pipeline.triage import generate_card


def _item(source_type="github"):
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


def _ctx():
    return ChangeContext(
        change_type="status_changed",
        changed_fields={"status": {"old": "a", "new": "b"}},
        change_summary="status changed a->b",
    )


@pytest.mark.asyncio
async def test_no_change_context_behaves_identically():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[]
    )
    await generate_card(llm, _item(), {"context": {}}, "github")
    llm.generate_triage_card.assert_called_once()
    _, kwargs = llm.generate_triage_card.call_args
    assert "change_context" not in kwargs or kwargs.get("change_context") is None


@pytest.mark.asyncio
async def test_change_context_passed_to_llm_default():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[]
    )
    await generate_card(llm, _item(), {"context": {}}, "github", change_context=_ctx())
    _, kwargs = llm.generate_triage_card.call_args
    assert kwargs["change_context"].change_type == "status_changed"


@pytest.mark.asyncio
async def test_change_context_passed_to_registered_generator():
    seen = {}

    class _Gen(CardContentGenerator):
        async def generate(
            self,
            llm,
            item,
            enrichment_context,
            *,
            memory_context=None,
            change_context=None,
        ):
            seen["ctx"] = change_context
            return {
                "content_schema": "diff.v1",
                "sections": {"summary": "s"},
                "card_body": "s",
                "summary": "s",
            }

    llm = AsyncMock()
    await generate_card(
        llm,
        _item("diff"),
        {"context": {}},
        "diff",
        content_generators={"diff": _Gen()},
        change_context=_ctx(),
    )
    assert seen["ctx"].change_type == "status_changed"


@pytest.mark.asyncio
async def test_template_fallback_is_change_aware_marked():
    # Generator raises -> template fallback; with change_context the template
    # card_content carries a "change" key and an "[Updated]" summary marker.
    class _Boom(CardContentGenerator):
        async def generate(self, *a, **k):
            raise RuntimeError("boom")

    llm = AsyncMock()
    card = await generate_card(
        llm,
        _item("diff"),
        {"context": {}},
        "diff",
        content_generators={"diff": _Boom()},
        change_context=_ctx(),
    )
    assert "change" in card.card_content
    assert card.card_content["summary"].startswith("[Updated]")
