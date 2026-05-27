# tests/test_claude_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from server.providers.llm.claude import ClaudeProvider
from server.models import ExtractedItem, ItemCategory, RawItem, FilterRule, Fact

@pytest.fixture
def provider():
    return ClaudeProvider(api_key="test", base_url="http://test")

@pytest.mark.asyncio
async def test_extract_parses_json_response(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='[{"summary": "Review PR", "category": "action_item", "source_context": "ctx"}]')]
    provider.client = AsyncMock()
    provider.client.messages.create = AsyncMock(return_value=mock_response)

    items = await provider.extract("some text", "diff")
    assert len(items) == 1
    assert items[0].summary == "Review PR"
    assert items[0].category == ItemCategory.ACTION_ITEM

@pytest.mark.asyncio
async def test_score_relevance_parses_scores(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"relevance": 85, "confidence": 90}')]
    provider.client = AsyncMock()
    provider.client.messages.create = AsyncMock(return_value=mock_response)

    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="test")
    item = ExtractedItem(summary="test", category=ItemCategory.ACTION_ITEM, source_context="", raw_item=raw)
    rel, conf = await provider.score_relevance(item, [], [])
    assert rel == 85
    assert conf == 90

@pytest.mark.asyncio
async def test_template_options_vary_by_source(provider):
    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="test")
    item = ExtractedItem(summary="test", category=ItemCategory.ACTION_ITEM, source_context="", raw_item=raw)
    provider.client = AsyncMock()
    card = await provider.generate_triage_card(item, {}, "diff")
    assert any("diff" in o.label.lower() for o in card.options)

    card2 = await provider.generate_triage_card(item, {}, "email")
    assert any("email" in o.label.lower() for o in card2.options)
