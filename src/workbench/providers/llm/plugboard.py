"""Transport-view instrumentation for plugboard (LLM gateway) calls.

A thin wrapper around ``messages.create`` that is the one layer where the
Anthropic response ``usage`` (tokens), the model string, and the calling
client identity are all in scope. Providers emit a ``PlugboardCallRecord`` to an
injected sink; they do NOT import ``workbench.telemetry.metrics`` (preserves provider
pluggability). See ADR 0049 / spec 3.3-3.4.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class PlugboardCallRecord:
    client: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_s: float = 0.0
    error_type: str | None = None
    item_count: int = 1


PlugboardSink = Callable[[PlugboardCallRecord], None]


async def record_plugboard_call(
    *,
    client: str,
    model: str,
    do_call: Callable[[], Awaitable[Any]],
    sink: PlugboardSink | None,
    item_count: int = 1,
) -> Any:
    """Run ``do_call`` (one messages.create), emitting a PlugboardCallRecord.

    Counts each HTTP attempt (so retries inflate the call count, by design). On
    error, records the call + error_type with zero tokens, then re-raises.
    When ``sink`` is None this is a transparent pass-through.
    """
    start = time.monotonic()
    try:
        resp = await do_call()
    except Exception as e:
        if sink is not None:
            sink(
                PlugboardCallRecord(
                    client=client,
                    model=model,
                    latency_s=time.monotonic() - start,
                    error_type=type(e).__name__,
                    item_count=item_count,
                )
            )
        raise
    if sink is not None:
        usage = getattr(resp, "usage", None)
        sink(
            PlugboardCallRecord(
                client=client,
                model=model,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0)
                or 0,
                latency_s=time.monotonic() - start,
                item_count=item_count,
            )
        )
    return resp
