"""generate_card stamps item_paths=(item_path,) on its LLM call (regression for
the unstamped bug); the engine records a triage_card link at the card's item
path after save_card."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem, ExtractedItem, ItemCategory, TriageCard
from workbench.pipeline.triage import generate_card

pytestmark = pytest.mark.asyncio


async def test_generate_card_stamps_item_path():
    captured = {}

    async def fake_card(
        item, ctx, source_type, memory_context=None, change_context=None
    ):
        captured["ctx"] = current_llm_call_context()
        return TriageCard(card_content={"summary": "s"})

    llm = MagicMock()
    llm.generate_triage_card = fake_card

    raw = RawItem(id="s1", source_type="t", source_label="", raw_text="x")
    item = ExtractedItem(
        summary="c",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )

    await generate_card(llm, item, {"context": {}}, "t", item_path="123.1")
    assert captured["ctx"].item_paths == ("123.1",)
