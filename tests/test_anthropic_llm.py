# tests/test_anthropic_llm.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.providers.llm.anthropic import AnthropicLLM
from workbench.domain import ExtractedItem, ItemCategory, RawItem, FilterRule, Fact


@pytest.fixture
def provider():
    config = AnthropicLLM.ProviderConfig(api_key="test", base_url="http://test")
    return AnthropicLLM(config)


@pytest.mark.asyncio
async def test_extract_parses_json_response(provider):
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='[{"summary": "Review PR", "category": "action_item", "source_context": "ctx"}]'
        )
    ]
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
    item = ExtractedItem(
        summary="test",
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=raw,
    )
    rel, conf = await provider.score_relevance(item, [], [])
    assert rel == 85
    assert conf == 90


@pytest.mark.asyncio
async def test_template_options_vary_by_source(provider):
    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="test")
    item = ExtractedItem(
        summary="test",
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=raw,
    )
    provider.client = AsyncMock()
    card = await provider.generate_triage_card(item, {}, "diff")
    assert any("diff" in o.label.lower() for o in card.options)

    card2 = await provider.generate_triage_card(item, {}, "email")
    assert any("email" in o.label.lower() for o in card2.options)


@pytest.mark.asyncio
async def test_call_with_retry_records_raw_request(monkeypatch):
    from types import SimpleNamespace
    from workbench.providers.llm.anthropic import AnthropicLLM

    seen = []

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(text="hello", type="text")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                model_dump=lambda mode="json": {
                    "content": [{"type": "text", "text": "hello"}]
                },
            )

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-x"
    llm.client = SimpleNamespace(messages=FakeMessages())
    llm._sink = seen.append

    out = await llm._call_with_retry("classify this item")
    assert out == "hello"
    rec = seen[-1]
    assert rec.raw_request["model"] == "claude-x"
    assert rec.raw_request["messages"] == [
        {"role": "user", "content": "classify this item"}
    ]
    assert rec.raw_request["max_tokens"] == 2000
