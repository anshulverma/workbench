"""Domain additions for cross-entity lineage: correlation_id on the LLM call
context + record, and the new Message model."""

from workbench.providers.llm.context import (
    LLMCallContext,
    llm_call_context,
    current_llm_call_context,
)
from workbench.domain.llm_calls import LlmCallRecord
from workbench.domain.messages import Message
from datetime import datetime, timezone


def test_context_has_correlation_id_default_none():
    ctx = LLMCallContext(origin="o", purpose="p", stage="s")
    assert ctx.correlation_id is None


def test_llm_call_context_helper_stamps_correlation_id():
    with llm_call_context(
        origin="filter",
        purpose="score_relevance",
        stage="filter",
        correlation_id="abc-123",
    ):
        ctx = current_llm_call_context()
        assert ctx.correlation_id == "abc-123"
        assert ctx.item_paths == ()


def test_llm_call_record_has_correlation_id():
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
        correlation_id="xyz",
    )
    assert rec.correlation_id == "xyz"


def test_message_model_defaults():
    m = Message(kind="card", direction="outbound", summary="card #5")
    assert m.id is None
    assert m.kind == "card"
    assert m.direction == "outbound"
    assert m.bot_message_id is None
    assert isinstance(m.created_at, datetime)


def test_message_exported_from_domain():
    from workbench.domain import Message as DomainMessage

    assert DomainMessage is Message
