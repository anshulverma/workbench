"""Test LLMCallContext contextvar for call provenance."""

from workbench.providers.llm.context import llm_call_context, current_llm_call_context


def test_context_set_and_clear():
    """Test basic context set and clear."""
    assert current_llm_call_context() is None
    with llm_call_context(origin="o", purpose="p", stage="filter"):
        c = current_llm_call_context()
        assert (c.origin, c.purpose, c.stage) == ("o", "p", "filter")
    assert current_llm_call_context() is None


def test_nested_context_restores_outer():
    """Test nested contexts restore outer context on exit."""
    with llm_call_context(origin="o1", purpose="p1", stage="extract"):
        with llm_call_context(origin="o2", purpose="p2", stage="triage"):
            assert current_llm_call_context().stage == "triage"
        assert current_llm_call_context().stage == "extract"


def test_llm_call_context_carries_item_paths():
    from workbench.providers.llm.context import (
        llm_call_context,
        current_llm_call_context,
    )

    with llm_call_context(
        origin="filter", purpose="score_relevance", stage="filter",
        item_paths=["123.1", "123.2"],
    ):
        ctx = current_llm_call_context()
        assert ctx.item_paths == ("123.1", "123.2")

    # default is empty tuple, and existing 3-arg call sites still work
    with llm_call_context(origin="o", purpose="p", stage="filter"):
        assert current_llm_call_context().item_paths == ()
