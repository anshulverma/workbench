"""Integration tests for Task 6: provenance context + body/subcall capture
wired at the pipeline LLM call sites.

These exercise the real provider methods (AnthropicLLM, LLMQueueScorer) with a
capturing sink and a fake Anthropic client, and assert that:
- batched paths emit one record with a per-item subcalls list (tokens_estimated)
- single calls capture bodies without estimation
- the pipeline filter stage actually enters the llm_call_context
- the per-item fallback inside a batch is marked is_fallback=True
"""

import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from workbench.providers.llm.anthropic import AnthropicLLM
from workbench.providers.queue_scorer.llm import LLMQueueScorer
from workbench.providers.llm.context import (
    llm_call_context,
    current_llm_call_context,
)
from workbench.domain import ExtractedItem, ItemCategory, RawItem

pytestmark = pytest.mark.asyncio


def _ctx(summary, sid):
    item = ExtractedItem(
        summary=summary,
        category=ItemCategory.ACTION_ITEM,
        source_context="",
        raw_item=RawItem(id=sid, source_type="email", source_label="", raw_text="x"),
    )
    return (item, [], [])


def _usage(input_tokens, output_tokens):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _resp(text, input_tokens=100, output_tokens=40):
    return SimpleNamespace(
        usage=_usage(input_tokens, output_tokens),
        content=[SimpleNamespace(text=text)],
    )


def _llm_with_sink(sink):
    llm = AnthropicLLM(AnthropicLLM.ProviderConfig(api_key="k"))
    llm._sink = sink
    return llm


def _scorer_with_sink(sink):
    s = LLMQueueScorer(LLMQueueScorer.ProviderConfig(api_key="k"))
    s._sink = sink
    return s


async def test_batched_relevance_emits_one_record_with_subcalls(monkeypatch):
    captured = []
    llm = _llm_with_sink(captured.append)

    array = [
        {"index": 0, "relevance": 80, "confidence": 90},
        {"index": 1, "relevance": 20, "confidence": 85},
    ]

    async def fake_create(**kwargs):
        return _resp(json.dumps(array), input_tokens=100, output_tokens=40)

    monkeypatch.setattr(llm.client.messages, "create", fake_create)

    with llm_call_context(origin="filter", purpose="score_relevance", stage="filter"):
        out = await llm.score_relevance_many([_ctx("a", "1"), _ctx("b", "2")])

    assert out == [(80, 90), (20, 85)]
    # exactly one record (one batched messages.create)
    assert len(captured) == 1
    rec = captured[0]
    assert rec.context is not None and rec.context.stage == "filter"
    assert rec.tokens_estimated is True
    assert rec.subcalls is not None and len(rec.subcalls) == 2
    for sc in rec.subcalls:
        assert sc["prompt"]
        assert sc["completion"]
        assert sc["structured"] is not None
        assert isinstance(sc["tokens_in"], int)
    # proportional split sums to the batch total (no leftover loss > rounding)
    total_in = sum(sc["tokens_in"] for sc in rec.subcalls)
    assert total_in == 100


async def test_single_relevance_call_not_estimated(monkeypatch):
    captured = []
    llm = _llm_with_sink(captured.append)

    async def fake_create(**kwargs):
        return _resp('{"relevance": 85, "confidence": 90}', 50, 10)

    monkeypatch.setattr(llm.client.messages, "create", fake_create)

    item, facts, rules = _ctx("solo", "1")
    with llm_call_context(origin="filter", purpose="score_relevance", stage="filter"):
        rel, conf = await llm.score_relevance(item, facts, rules)

    assert (rel, conf) == (85, 90)
    assert len(captured) == 1
    rec = captured[0]
    assert rec.tokens_estimated is False
    assert rec.completion is not None
    assert rec.input_prompt is not None
    assert rec.context.stage == "filter"


async def test_pipeline_filter_stage_enters_context(monkeypatch):
    """The real pipeline filter helper sets stage=filter around the call."""
    from workbench.pipeline.filter import score_and_decide

    seen = {}

    class FakeLLM:
        async def score_relevance(self, item, facts, rules):
            ctx = current_llm_call_context()
            seen["stage"] = ctx.stage if ctx else None
            seen["origin"] = ctx.origin if ctx else None
            return 80, 90

    class FakeMemory:
        async def query_preferences(self, *a):
            return []

        async def query_entity(self, *a):
            return None

        async def query_relationships(self, *a):
            return []

    class FakeRules:
        async def get_rules(self):
            return []

        async def get_source_rules(self, st):
            return []

    item, _, _ = _ctx("x", "1")
    action, rel, conf = await score_and_decide(
        FakeLLM(), FakeMemory(), FakeRules(), item
    )
    assert seen["stage"] == "filter"
    assert seen["origin"] == "filter"
    assert (rel, conf) == (80, 90)


async def test_batch_fallback_marks_is_fallback(monkeypatch):
    captured = []
    llm = _llm_with_sink(captured.append)

    # batch returns only index 0; index 1 missing -> per-item fallback call
    async def fake_create(**kwargs):
        content = kwargs["messages"][0]["content"]
        if "JSON array" in content:
            return _resp('[{"index":0,"relevance":80,"confidence":90}]', 100, 40)
        # single fallback call
        return _resp('{"relevance": 55, "confidence": 55}', 20, 5)

    monkeypatch.setattr(llm.client.messages, "create", fake_create)

    with llm_call_context(origin="filter", purpose="score_relevance", stage="filter"):
        out = await llm.score_relevance_many([_ctx("a", "1"), _ctx("b", "2")])

    assert out[0] == (80, 90)
    assert out[1] == (55, 55)
    # one batch record + one fallback record
    fallback_recs = [r for r in captured if r.is_fallback]
    assert len(fallback_recs) == 1
    batch_recs = [r for r in captured if not r.is_fallback]
    assert len(batch_recs) == 1
    # batch row keeps only the successfully-parsed index
    assert len(batch_recs[0].subcalls) == 1


async def test_batched_urgency_emits_subcalls(monkeypatch):
    captured = []
    s = _scorer_with_sink(captured.append)

    array = [{"index": 0, "urgency": 70}, {"index": 1, "urgency": 10}]

    async def fake_create(**kwargs):
        return _resp(json.dumps(array), 80, 20)

    monkeypatch.setattr(s.client.messages, "create", fake_create)

    with llm_call_context(
        origin="queue_scorer", purpose="score_urgency", stage="scoring"
    ):
        out = await s.score_urgency_many([("t1", {"a": 1}), ("t2", {})])

    assert out == [70, 10]
    assert len(captured) == 1
    rec = captured[0]
    assert rec.context.stage == "scoring"
    assert rec.tokens_estimated is True
    assert len(rec.subcalls) == 2
    for sc in rec.subcalls:
        assert sc["prompt"]
        assert sc["structured"] is not None


async def test_single_urgency_not_estimated(monkeypatch):
    captured = []
    s = _scorer_with_sink(captured.append)

    async def fake_create(**kwargs):
        return _resp('{"urgency": 60}', 30, 5)

    monkeypatch.setattr(s.client.messages, "create", fake_create)

    with llm_call_context(
        origin="queue_scorer", purpose="score_urgency", stage="scoring"
    ):
        out = await s.score_urgency("hello", {"a": 1})

    assert out == 60
    assert len(captured) == 1
    rec = captured[0]
    assert rec.tokens_estimated is False
    assert rec.completion is not None
    assert rec.input_prompt is not None


async def test_extract_captures_body(monkeypatch):
    captured = []
    llm = _llm_with_sink(captured.append)

    async def fake_create(**kwargs):
        return _resp(
            '[{"summary": "Do X", "category": "action_item", "source_context": "c"}]',
            70,
            20,
        )

    monkeypatch.setattr(llm.client.messages, "create", fake_create)

    with llm_call_context(origin="extract", purpose="extract", stage="extract"):
        items = await llm.extract("some long content here", "email")

    assert len(items) == 1
    assert len(captured) == 1
    rec = captured[0]
    assert rec.context.stage == "extract"
    assert rec.completion is not None
    assert rec.input_prompt is not None
    assert rec.tokens_estimated is False


async def test_interpret_response_captures_context(monkeypatch):
    from workbench.domain import TriageCard, TriageOption

    captured = []
    llm = _llm_with_sink(captured.append)

    tool_block = SimpleNamespace(
        type="tool_use",
        name="interpret_response",
        input={
            "system_actions": [{"action": "add_todo", "details": {"priority": "P1"}}],
            "explanation": "done",
        },
    )

    async def fake_create(**kwargs):
        return SimpleNamespace(usage=_usage(50, 10), content=[tool_block])

    monkeypatch.setattr(llm.client.messages, "create", fake_create)

    card = TriageCard(
        card_content={"summary": "s", "source_type": "email"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    with llm_call_context(origin="aggregate", purpose="interpret", stage="aggregate"):
        result = await llm.interpret_triage_response(card, "make it P1")

    assert result.system_actions[0].action == "add_todo"
    assert len(captured) == 1
    rec = captured[0]
    assert rec.context.stage == "aggregate"
    assert rec.input_prompt is not None
    # structured captures the tool-result input
    assert rec.structured is not None
