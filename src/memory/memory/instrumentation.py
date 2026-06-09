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

import time
from typing import Any


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


def instrument_llm_client(
    inner: Any,
    metrics: Any,
    model: str,
    *,
    aggregator: "MemoryUsageAggregator | None" = None,
    client: str = "memory",
) -> Any:
    """Wrap ``inner``'s generate method in place, recording plugboard metrics.

    Returns ``inner`` (same object/type). No-op-safe: if no generate method is
    found, ``inner`` is returned unchanged.
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
            raise
        elapsed = time.monotonic() - start
        metrics.plugboard_calls.labels(client=client, model=model).inc()
        metrics.plugboard_call_seconds.labels(client=client, model=model).observe(
            elapsed
        )
        if aggregator is not None:
            aggregator.record(model, error=False)
        return result

    setattr(inner, method_name, _wrapper)
    return inner
