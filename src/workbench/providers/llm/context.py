"""LLM call context for ambient provenance tracking.

Provides a contextvars-based mechanism to carry origin/purpose/stage metadata
through LLM calls without threading parameters. Task-local so concurrent
pipeline workers don't cross-contaminate.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallContext:
    """Provenance metadata for an LLM call.

    Attributes:
        origin: Where the call originates (e.g., "gchat_source", "triage_pipeline").
        purpose: Why we're calling the LLM (e.g., "extract_events", "score_urgency").
        stage: Pipeline stage (e.g., "extract", "filter", "triage").
        item_paths: Real item path ids this call concerns (one per item; a
            batched call carries all of them). Empty when no lineage is stamped.
    """

    origin: str
    purpose: str
    stage: str
    item_paths: tuple[str, ...] = ()


# Module-level contextvar for ambient context
_current: ContextVar[LLMCallContext | None] = ContextVar(
    "llm_call_context", default=None
)


def current_llm_call_context() -> LLMCallContext | None:
    """Get the current LLM call context, or None if not set."""
    return _current.get()


@contextmanager
def llm_call_context(
    *,
    origin: str,
    purpose: str,
    stage: str,
    item_paths: tuple[str, ...] | list[str] = (),
):
    """Set LLM call context for the duration of this block.

    Args:
        origin: Where the call originates (e.g., "gchat_source").
        purpose: Why we're calling the LLM (e.g., "extract_events").
        stage: Pipeline stage (e.g., "extract", "filter", "triage").
        item_paths: Real item path ids this call concerns. A batched call may
            carry several. Defaults to empty (no lineage stamped).

    Yields:
        None

    Example:
        with llm_call_context(origin="gchat", purpose="extract", stage="extract"):
            # LLM calls here can read current_llm_call_context()
            ...
    """
    context = LLMCallContext(
        origin=origin, purpose=purpose, stage=stage, item_paths=tuple(item_paths)
    )
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)
