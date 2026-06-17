"""Instrument the Graphiti LLM client for plugboard metrics.

Graphiti owns the LLM client and calls it internally, so we wrap the client
*instance* in place (type-preserving — passes any isinstance checks Graphiti
makes — and imports nothing from ``graphiti_core``, so this module is testable
without it). We wrap the public ``generate_response`` (falling back to
``_generate_response``) so each logical LLM call is counted once.

Calls/latency/errors are recorded authoritatively; tokens are best-effort —
Graphiti's ``generate_response`` returns a parsed dict that typically does NOT
expose Anthropic ``usage``, so the token counter usually stays unincremented
(documented degradation per ADR 0050).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from memory.llm_capture import (
    LlmCallWriter,
    build_memory_row,
    extract_completion_text,
    extract_messages,
)

logger = logging.getLogger(__name__)


def _extract_token_usage(result: Any) -> tuple[int, int, bool]:
    """Best-effort token extraction from a Graphiti result.

    Graphiti's ``generate_response`` typically returns a parsed dict WITHOUT
    Anthropic ``usage``, so this usually returns ``(0, 0, False)`` (tokens
    unavailable => the row is marked ``tokens_estimated``). If a ``usage`` block
    is present we read input/output tokens from it.
    """
    try:
        usage = None
        if isinstance(result, dict):
            usage = result.get("usage")
        else:
            usage = getattr(result, "usage", None)
        if usage is None:
            return 0, 0, False
        if isinstance(usage, dict):
            tin = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            tout = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        else:
            tin = getattr(usage, "input_tokens", 0) or 0
            tout = getattr(usage, "output_tokens", 0) or 0
        return int(tin), int(tout), True
    except Exception:
        return 0, 0, False


class MemoryUsageAggregator:
    """Per-interval calls/errors counts keyed by model, for the summary log."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, int]] = {}

    def record(self, model: str, *, error: bool) -> None:
        bucket = self._data.get(model)
        if bucket is None:
            bucket = {"calls": 0, "errors": 0}
            self._data[model] = bucket
        bucket["calls"] += 1
        if error:
            bucket["errors"] += 1

    def drain(self) -> dict[str, dict[str, int]]:
        snapshot = self._data
        self._data = {}
        return snapshot


def _messages_from_call(args: tuple, kwargs: dict) -> Any:
    """Best-effort: locate the messages argument Graphiti passes to generate."""
    if "messages" in kwargs:
        return kwargs["messages"]
    if args:
        return args[0]
    return None


def _spawn_capture(writer: "LlmCallWriter", row: dict) -> None:
    """Fire-and-forget the cross-DB write; never block or fail the LLM call."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(writer.write(row))
        # Avoid "task was never retrieved" warnings; errors are swallowed inside
        # writer.write itself.
        task.add_done_callback(lambda t: t.exception())
    except Exception:
        logger.debug("llm_capture: failed to spawn writer task", exc_info=True)


def instrument_llm_client(
    inner: Any,
    metrics: Any,
    model: str,
    *,
    aggregator: "MemoryUsageAggregator | None" = None,
    client: str = "memory",
    writer: "LlmCallWriter | None" = None,
) -> Any:
    """Wrap ``inner``'s generate method in place, recording plugboard metrics.

    Returns ``inner`` (same object/type). No-op-safe: if no generate method is
    found, ``inner`` is returned unchanged.

    When ``writer`` is supplied (and active), each call additionally captures
    the system/input prompt, completion, structured result, and best-effort
    tokens, and INSERTs a full-fidelity row into the workbench ``llm_calls``
    table. The capture is fire-and-forget and best-effort: it never delays or
    breaks the underlying LLM call (ADR 0059).
    """
    method_name = (
        "generate_response"
        if hasattr(inner, "generate_response")
        else "_generate_response" if hasattr(inner, "_generate_response") else None
    )
    if method_name is None:
        return inner

    original = getattr(inner, method_name)

    async def _wrapper(*args, **kwargs):
        start = time.monotonic()
        started_at = datetime.now(timezone.utc)
        try:
            result = await original(*args, **kwargs)
        except Exception as e:
            elapsed = time.monotonic() - start
            metrics.plugboard_calls.labels(client=client, model=model).inc()
            metrics.plugboard_errors.labels(
                client=client, model=model, error_type=type(e).__name__
            ).inc()
            metrics.plugboard_call_seconds.labels(client=client, model=model).observe(
                elapsed
            )
            if aggregator is not None:
                aggregator.record(model, error=True)
            if writer is not None and writer.active:
                _capture(
                    writer,
                    started_at=started_at,
                    elapsed=elapsed,
                    model=model,
                    args=args,
                    kwargs=kwargs,
                    result=None,
                    status="error",
                    error_type=type(e).__name__,
                )
            raise
        elapsed = time.monotonic() - start
        metrics.plugboard_calls.labels(client=client, model=model).inc()
        metrics.plugboard_call_seconds.labels(client=client, model=model).observe(
            elapsed
        )
        if aggregator is not None:
            aggregator.record(model, error=False)
        if writer is not None and writer.active:
            _capture(
                writer,
                started_at=started_at,
                elapsed=elapsed,
                model=model,
                args=args,
                kwargs=kwargs,
                result=result,
                status="ok",
                error_type=None,
            )
        return result

    setattr(inner, method_name, _wrapper)
    return inner


def _capture(
    writer: "LlmCallWriter",
    *,
    started_at: datetime,
    elapsed: float,
    model: str,
    args: tuple,
    kwargs: dict,
    result: Any,
    status: str,
    error_type: str | None,
) -> None:
    """Build the row and dispatch the best-effort cross-DB write. Never raises."""
    try:
        messages = _messages_from_call(args, kwargs)
        system_prompt, input_prompt = extract_messages(messages)
        completion = extract_completion_text(result)
        structured = result if isinstance(result, dict) else None
        tokens_in, tokens_out, tokens_available = _extract_token_usage(result)
        row = build_memory_row(
            started_at=started_at,
            model=model,
            latency_ms=int(elapsed * 1000),
            status=status,
            error_type=error_type,
            system_prompt=system_prompt,
            input_prompt=input_prompt,
            completion=completion,
            structured=structured,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_available=tokens_available,
        )
        _spawn_capture(writer, row)
    except Exception:
        logger.debug("llm_capture: failed to build/dispatch row", exc_info=True)
