import pytest
from unittest.mock import AsyncMock

from workbench.providers.llm.anthropic import AnthropicLLM
from workbench.domain import ExtractedItem, ItemCategory, RawItem
from workbench.pipeline.filter import decide_from_score


def _ctx(summary, sid):
    item = ExtractedItem(
        summary=summary,
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=RawItem(id=sid, source_type="email", source_label="", raw_text="x"),
    )
    return (item, [], [])


def _llm():
    return AnthropicLLM(AnthropicLLM.ProviderConfig(api_key="k"))


@pytest.mark.asyncio
async def test_score_relevance_many_parses_indexed(monkeypatch):
    llm = _llm()

    async def fake_call(prompt, **k):
        return (
            '[{"index":0,"relevance":80,"confidence":90},'
            '{"index":1,"relevance":20,"confidence":85}]'
        )

    monkeypatch.setattr(llm, "_call_with_retry", fake_call)
    out = await llm.score_relevance_many([_ctx("a", "1"), _ctx("b", "2")])
    assert out == [(80, 90), (20, 85)]


@pytest.mark.asyncio
async def test_score_relevance_many_falls_back_on_missing_index(monkeypatch):
    llm = _llm()

    async def fake_batch(prompt, **k):
        return '[{"index":0,"relevance":80,"confidence":90}]'  # missing index 1

    monkeypatch.setattr(llm, "_call_with_retry", fake_batch)
    llm.score_relevance = AsyncMock(return_value=(55, 55))
    out = await llm.score_relevance_many([_ctx("a", "1"), _ctx("b", "2")])
    assert out[0] == (80, 90)
    assert out[1] == (55, 55)  # per-item fallback for the missing index
    llm.score_relevance.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_relevance_many_whole_batch_failure_falls_back(monkeypatch):
    llm = _llm()

    async def boom(prompt, **k):
        raise ValueError("api down")

    monkeypatch.setattr(llm, "_call_with_retry", boom)
    llm.score_relevance = AsyncMock(return_value=(42, 42))
    out = await llm.score_relevance_many([_ctx("a", "1"), _ctx("b", "2")])
    assert out == [(42, 42), (42, 42)]
    assert llm.score_relevance.await_count == 2


@pytest.mark.asyncio
async def test_score_relevance_many_chunks(monkeypatch):
    llm = _llm()
    calls = []

    async def fake_call(prompt, **k):
        calls.append(k.get("item_count"))
        # one result per item in this chunk, indices 0..n-1
        import json

        n = k.get("item_count")
        return json.dumps(
            [{"index": i, "relevance": 60, "confidence": 80} for i in range(n)]
        )

    monkeypatch.setattr(llm, "_call_with_retry", fake_call)
    out = await llm.score_relevance_many(
        [_ctx(str(i), str(i)) for i in range(5)], max_batch_size=2
    )
    assert len(out) == 5
    assert all(r == (60, 80) for r in out)
    assert calls == [2, 2, 1]  # chunked 2+2+1


def test_decide_from_score_thresholds():
    assert decide_from_score(80, 90) == "auto_include"
    assert decide_from_score(10, 90) == "auto_drop"
    assert decide_from_score(50, 90) == "triage"
    assert decide_from_score(80, 50) == "triage"  # low confidence -> triage


# --- S5: batch score_urgency ---

def _scorer():
    from workbench.providers.queue_scorer.llm import LLMQueueScorer

    return LLMQueueScorer(LLMQueueScorer.ProviderConfig(api_key="k"))


@pytest.mark.asyncio
async def test_score_urgency_many_parses_indexed(monkeypatch):
    from types import SimpleNamespace

    s = _scorer()

    async def fake_create(**kwargs):
        return SimpleNamespace(
            usage=None,
            content=[
                SimpleNamespace(
                    text='[{"index":0,"urgency":70},{"index":1,"urgency":10}]'
                )
            ],
        )

    monkeypatch.setattr(s.client.messages, "create", fake_create)
    out = await s.score_urgency_many([("t1", {"a": 1}), ("t2", {})])
    assert out == [70, 10]


@pytest.mark.asyncio
async def test_score_urgency_many_falls_back_on_missing(monkeypatch):
    from types import SimpleNamespace

    s = _scorer()

    async def fake_create(**kwargs):
        return SimpleNamespace(
            usage=None,
            content=[SimpleNamespace(text='[{"index":0,"urgency":70}]')],
        )

    monkeypatch.setattr(s.client.messages, "create", fake_create)
    s.score_urgency = AsyncMock(return_value=33)
    out = await s.score_urgency_many([("t1", {"a": 1}), ("t2", {"b": 2})])
    assert out[0] == 70
    assert out[1] == 33  # per-item fallback for missing index
    s.score_urgency.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_urgency_many_max_tokens_scales(monkeypatch):
    from types import SimpleNamespace

    s = _scorer()
    seen = {}

    async def fake_create(**kwargs):
        seen["max_tokens"] = kwargs["max_tokens"]
        import json

        n = len(json.loads(kwargs["messages"][0]["content"].split("Items:\n")[1]))
        return SimpleNamespace(
            usage=None,
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        [{"index": i, "urgency": 50} for i in range(n)]
                    )
                )
            ],
        )

    monkeypatch.setattr(s.client.messages, "create", fake_create)
    out = await s.score_urgency_many([("t", {"a": 1})] * 3)
    assert out == [50, 50, 50]
    assert seen["max_tokens"] == min(4096, 40 * 3 + 100)  # scales with batch
