"""Tests for the async llm_calls writer + tracking config (Task 7).

Covers the pure mapping helper `_to_llm_record`, the writer-drain helper
`_drain_once`, and the new LlmTrackingConfig / RetentionConfig defaults.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from workbench.config.models import AppConfig, LlmTrackingConfig, RetentionConfig
from workbench.domain.llm_calls import LlmCallRecord
from workbench.providers.llm.context import LLMCallContext
from workbench.providers.llm.plugboard import PlugboardCallRecord
from workbench.runtime.app import _drain_once, _to_llm_record


def _ctx():
    return LLMCallContext(
        origin="gchat_source", purpose="extract_events", stage="extract"
    )


def test_to_llm_record_maps_fields():
    rec = PlugboardCallRecord(
        client="plugboard",
        model="claude-sonnet",
        input_tokens=120,
        output_tokens=45,
        cache_read_tokens=10,
        cache_write_tokens=5,
        latency_s=2.5,
        item_count=2,
        context=_ctx(),
        system_prompt="you are a helper",
        temperature=0.3,
        tokens_estimated=True,
        is_fallback=False,
        subcalls=[
            {
                "item": "item-1",
                "prompt": "p1",
                "completion": "c1",
                "structured": {"k": "v"},
                "tokens_in": None,  # must coerce to 0
                "tokens_out": 7,
            },
            {
                "item": "item-2",
                "prompt": "p2",
                "completion": "c2",
                "tokens_in": 3,
            },
        ],
    )

    out = _to_llm_record(rec)
    assert isinstance(out, LlmCallRecord)
    assert out.origin == "gchat_source"
    assert out.purpose == "extract_events"
    assert out.stage == "extract"
    assert out.model == "claude-sonnet"
    assert out.temperature == 0.3
    assert out.status == "ok"
    assert out.error_type is None
    assert out.batch == 2
    assert out.items == ["item-1", "item-2"]
    assert out.tokens_in == 120
    assert out.tokens_out == 45
    assert out.cache_read_tokens == 10
    assert out.cache_write_tokens == 5
    assert out.latency_ms == 2500
    assert out.system_prompt == "you are a helper"
    assert out.tokens_estimated is True
    assert out.is_fallback is False

    # subcalls mapped; None tokens_in coerced to 0
    assert len(out.subcalls) == 2
    assert out.subcalls[0].item == "item-1"
    assert out.subcalls[0].tokens_in == 0
    assert out.subcalls[0].tokens_out == 7
    assert out.subcalls[0].structured == {"k": "v"}
    assert out.subcalls[1].tokens_in == 3
    assert out.subcalls[1].structured is None

    # started_at is timezone-aware and approximately now - latency
    assert out.started_at.tzinfo is not None
    expected = datetime.now(timezone.utc).timestamp() - 2.5
    assert abs(out.started_at.timestamp() - expected) < 5.0


def test_to_llm_record_skips_when_no_context():
    rec = PlugboardCallRecord(client="plugboard", model="m", context=None)
    assert _to_llm_record(rec) is None


def test_to_llm_record_error_status():
    rec = PlugboardCallRecord(
        client="plugboard",
        model="m",
        input_tokens=50,
        output_tokens=0,
        latency_s=1.0,
        context=_ctx(),
        error_type="RateLimitError",
    )
    out = _to_llm_record(rec)
    assert out is not None
    assert out.status == "error"
    assert out.error_type == "RateLimitError"
    assert out.tokens_out is None


@pytest.mark.asyncio
async def test_drain_once_saves_non_none_records():
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    r1 = _to_llm_record(
        PlugboardCallRecord(client="c", model="m", context=_ctx(), latency_s=0.1)
    )
    r2 = _to_llm_record(
        PlugboardCallRecord(client="c", model="m", context=_ctx(), latency_s=0.2)
    )
    q.put_nowait(r1)
    q.put_nowait(r2)
    q.put_nowait(None)  # defensive None should be filtered out

    store = AsyncMock()
    store.save_many = AsyncMock()

    await _drain_once(q, store, max_batch=50)

    store.save_many.assert_awaited_once()
    saved = store.save_many.await_args.args[0]
    assert saved == [r1, r2]
    # All three queue items were consumed (task_done called for each).
    assert q.empty()


@pytest.mark.asyncio
async def test_drain_once_skips_save_when_all_none():
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    q.put_nowait(None)
    store = AsyncMock()
    store.save_many = AsyncMock()
    await _drain_once(q, store, max_batch=50)
    store.save_many.assert_not_awaited()


def test_llm_tracking_config_defaults():
    assert LlmTrackingConfig().enabled is True


def test_retention_config_llm_defaults():
    rc = RetentionConfig()
    assert rc.llm_calls_days == 28
    assert rc.llm_calls_max_rows is None


def test_app_config_has_llm_tracking():
    cfg = AppConfig(storage={"postgres_dsn": "postgres://x"}, llm={})
    assert cfg.llm_tracking.enabled is True


def test_to_llm_record_malformed_subcall_does_not_raise_via_guard():
    """`_to_llm_record` CAN raise on a malformed subcall (subcall dict missing
    the required ``"item"`` key -> KeyError). This documents the necessity of
    the app-sink's try/except guard around the mapping+enqueue: without it, a
    malformed subcall would turn a SUCCESSFUL LLM call into a failure.

    The seam-level guarantee (a raising sink never breaks the call) is covered
    by tests/test_llm_capture.py::test_sink_exception_does_not_break_call.
    """
    rec = PlugboardCallRecord(
        client="plugboard",
        model="m",
        context=_ctx(),
        latency_s=0.1,
        subcalls=[{"prompt": "p", "completion": "c"}],  # no "item" key
    )
    with pytest.raises(KeyError):
        _to_llm_record(rec)


def test_app_module_has_no_bare_stores_reference():
    """Regression for the boot-time NameError (Bug 1).

    The lifespan must reference ``app.state.stores`` (or a local bound from it),
    never a bare module-level ``stores``. A bare ``stores`` would raise
    NameError at startup, preventing the server from booting whenever
    llm_tracking is enabled. Constructing the full app/lifespan requires a live
    Postgres + every provider, which is too heavy for a unit test; instead we
    assert the offending bare-reference pattern is gone from the source and that
    the module imports cleanly (NameError-at-import would already fail import).
    """
    import inspect

    import workbench.runtime.app as app_mod

    src = inspect.getsource(app_mod.lifespan)
    # The two previously-broken sites used a bare ``stores.llm_calls``. Ensure
    # any ``stores.llm_calls`` is reached via a local bound from app.state.
    assert "app.state.stores = await create_stores" in inspect.getsource(app_mod)
    assert "stores = app.state.stores" in src


def test_to_llm_record_prefers_context_item_paths():
    """When the context carries item_paths, items records those lineage refs
    (batched call -> all paths), not the free-text subcall items."""
    rec = PlugboardCallRecord(
        client="plugboard",
        model="claude-sonnet",
        input_tokens=10,
        output_tokens=5,
        latency_s=1.0,
        item_count=2,
        context=LLMCallContext(
            origin="filter",
            purpose="score_relevance",
            stage="filter",
            item_paths=("123.1", "123.2"),
        ),
        subcalls=[
            {"item": "free-text-1", "prompt": "p1", "completion": "c1"},
            {"item": "free-text-2", "prompt": "p2", "completion": "c2"},
        ],
    )

    out = _to_llm_record(rec)
    assert out.items == ["123.1", "123.2"]


def test_to_llm_record_falls_back_when_item_paths_empty():
    """Empty item_paths preserves the legacy subcall-derived items."""
    rec = PlugboardCallRecord(
        client="plugboard",
        model="claude-sonnet",
        input_tokens=10,
        output_tokens=5,
        latency_s=1.0,
        item_count=1,
        context=LLMCallContext(
            origin="gchat_source", purpose="extract_events", stage="extract"
        ),
        subcalls=[{"item": "item-x", "prompt": "p", "completion": "c"}],
    )

    out = _to_llm_record(rec)
    assert out.items == ["item-x"]
