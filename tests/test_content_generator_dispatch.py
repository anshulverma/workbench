import pytest
from unittest.mock import AsyncMock
from workbench.models import ExtractedItem, RawItem, ItemCategory, TriageCard
from workbench.pipeline.content_generator import CardContentGenerator
from workbench.pipeline.triage import generate_card


def _item(source_type="diff") -> ExtractedItem:
    raw = RawItem(id="i1", source_type=source_type, source_label="l", raw_text="{}")
    return ExtractedItem(
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


class _StubGen(CardContentGenerator):
    def __init__(self):
        self.called = False

    async def generate(
        self, llm, item, enrichment_context, *, memory_context=None, change_context=None
    ):
        self.called = True
        return {
            "content_schema": "diff.v1",
            "sections": {"summary": "from generator"},
            "card_body": "body",
            "summary": "from generator",
        }


@pytest.mark.asyncio
async def test_dispatches_to_registered_generator_by_source_type():
    llm = AsyncMock()
    gen = _StubGen()
    card = await generate_card(
        llm,
        _item("diff"),
        {"context": {}},
        "diff",
        content_generators={"diff": gen},
    )
    assert gen.called is True
    assert card.card_content["content_schema"] == "diff.v1"
    assert card.card_content["sections"]["summary"] == "from generator"
    llm.generate_triage_card.assert_not_called()


@pytest.mark.asyncio
async def test_unregistered_source_type_uses_llm_default():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x", "source_type": "github"},
        options=[],
    )
    card = await generate_card(
        llm,
        _item("github"),
        {"context": {}},
        "github",
        content_generators={"diff": _StubGen()},
    )
    llm.generate_triage_card.assert_called_once()
    assert "content_schema" not in card.card_content


@pytest.mark.asyncio
async def test_no_generators_arg_preserves_legacy_behavior():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[]
    )
    card = await generate_card(llm, _item("github"), {"context": {}}, "github")
    llm.generate_triage_card.assert_called_once()


@pytest.mark.asyncio
async def test_generator_returning_summary_only_envelope_skips_sections():
    llm = AsyncMock()

    class _SummaryOnly(CardContentGenerator):
        async def generate(
            self,
            llm,
            item,
            enrichment_context,
            *,
            memory_context=None,
            change_context=None,
        ):
            return {"card_body": "fallback summary", "summary": "fallback summary"}

    card = await generate_card(
        llm,
        _item("diff"),
        {"context": {}},
        "diff",
        content_generators={"diff": _SummaryOnly()},
    )
    assert "sections" not in card.card_content
    assert card.card_content["summary"] == "fallback summary"
