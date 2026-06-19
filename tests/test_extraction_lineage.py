"""extract_items stamps item_paths=(root_path,) so the extraction LLM call links
the root (regression for the empty-items bug)."""

import pytest
from unittest.mock import AsyncMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.pipeline.extraction import extract_items

pytestmark = pytest.mark.asyncio


async def test_extract_items_stamps_root_path():
    captured = {}

    async def fake_extract(raw_text, source_type):
        captured["ctx"] = current_llm_call_context()
        return []

    llm = AsyncMock()
    llm.extract = fake_extract
    await extract_items(llm, "some long enough raw text", "diff", root_path="123")
    assert captured["ctx"].item_paths == ("123",)


async def test_extract_items_no_root_path_stamps_empty():
    captured = {}

    async def fake_extract(raw_text, source_type):
        captured["ctx"] = current_llm_call_context()
        return []

    llm = AsyncMock()
    llm.extract = fake_extract
    await extract_items(llm, "some long enough raw text", "diff")
    assert captured["ctx"].item_paths == ()
