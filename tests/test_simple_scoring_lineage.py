"""Non-batched score_and_decide stamps a correlation_id and returns it so the
caller can record_by_correlation the one child path after allocate_child
(regression for the empty-items bug on the simple site)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem, ExtractedItem, ItemCategory
from workbench.pipeline.filter import score_and_decide

pytestmark = pytest.mark.asyncio


async def test_score_and_decide_stamps_and_returns_correlation_id():
    captured = {}

    async def fake_score(item, facts, rules):
        captured["ctx"] = current_llm_call_context()
        return 90, 90

    llm = MagicMock()
    llm.score_relevance = fake_score

    memory = AsyncMock()
    memory.query_preferences = AsyncMock(return_value=[])
    memory.query_entity = AsyncMock(return_value=None)
    memory.query_relationships = AsyncMock(return_value=[])

    rules = AsyncMock()
    rules.get_rules = AsyncMock(return_value=[])
    rules.get_source_rules = AsyncMock(return_value=[])

    raw = RawItem(id="s1", source_type="t", source_label="", raw_text="x")
    item = ExtractedItem(
        summary="c",
        category=ItemCategory.INFORMATIONAL,
        source_context="",
        raw_item=raw,
    )

    action, relevance, confidence, correlation_id = await score_and_decide(
        llm, memory, rules, item
    )
    assert action == "auto_include"
    assert correlation_id is not None
    assert captured["ctx"].correlation_id == correlation_id
    assert captured["ctx"].item_paths == ()
