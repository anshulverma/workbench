# Source-link plumbing: generate_card() lifts source_ref / source_url off the
# RawItem and into card_content for every generation path (registered generator,
# default LLM, and template fallback), so the UI can render a "open in source"
# link and a source-type badge regardless of which path produced the card.

import pytest
from unittest.mock import AsyncMock

from workbench.domain import ExtractedItem, RawItem, ItemCategory, TriageCard
from workbench.pipeline.content_generator import CardContentGenerator
from workbench.pipeline.triage import generate_card


def _item(source_type="diff", *, source_ref=None, source_url=None) -> ExtractedItem:
    raw = RawItem(
        id="i1",
        source_type=source_type,
        source_label="l",
        raw_text="{}",
        source_ref=source_ref,
        source_url=source_url,
    )
    return ExtractedItem(
        summary="s",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )


def test_rawitem_source_fields_default_to_none():
    raw = RawItem(id="i", source_type="diff", source_label="l", raw_text="{}")
    assert raw.source_ref is None
    assert raw.source_url is None


class _StubGen(CardContentGenerator):
    async def generate(
        self, llm, item, enrichment_context, *, memory_context=None, change_context=None
    ):
        return {
            "source_type": "diff",
            "card_body": "body",
            "summary": "from generator",
        }


@pytest.mark.asyncio
async def test_generator_path_gets_source_ref_and_url_injected():
    llm = AsyncMock()
    card = await generate_card(
        llm,
        _item("diff", source_ref="D123456", source_url="https://x/D123456"),
        {"context": {}},
        "diff",
        content_generators={"diff": _StubGen()},
    )
    assert card.card_content["source_ref"] == "D123456"
    assert card.card_content["source_url"] == "https://x/D123456"
    assert card.card_content["source_type"] == "diff"


@pytest.mark.asyncio
async def test_default_llm_path_gets_source_ref_and_url_injected():
    llm = AsyncMock()
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"card_body": "x", "summary": "x"}, options=[]
    )
    card = await generate_card(
        llm,
        _item("meta_tasks", source_ref="T9999", source_url="https://x/?t=9999"),
        {"context": {}},
        "meta_tasks",
    )
    assert card.card_content["source_ref"] == "T9999"
    assert card.card_content["source_url"] == "https://x/?t=9999"
    # source_type is backfilled even when the LLM path omitted it.
    assert card.card_content["source_type"] == "meta_tasks"


@pytest.mark.asyncio
async def test_template_fallback_gets_source_ref_and_url_injected():
    llm = AsyncMock()
    llm.generate_triage_card.side_effect = RuntimeError("llm down")
    card = await generate_card(
        llm,
        _item("github", source_ref="#42", source_url="https://gh/pr/42"),
        {"context": {}},
        "github",
    )
    assert card.card_content["source_ref"] == "#42"
    assert card.card_content["source_url"] == "https://gh/pr/42"


@pytest.mark.asyncio
async def test_missing_source_fields_leave_card_content_clean():
    llm = AsyncMock()
    card = await generate_card(
        llm,
        _item("diff"),  # no source_ref / source_url
        {"context": {}},
        "diff",
        content_generators={"diff": _StubGen()},
    )
    assert "source_ref" not in card.card_content
    assert "source_url" not in card.card_content
