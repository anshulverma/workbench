"""Transport-view instrumentation for plugboard (LLM gateway) calls.

A thin wrapper around ``messages.create`` that is the one layer where the
Anthropic response ``usage`` (tokens), the model string, and the calling
client identity are all in scope. Providers emit a ``PlugboardCallRecord`` to an
injected sink; they do NOT import ``workbench.telemetry.metrics`` (preserves provider
pluggability). See ADR 0049 / spec 3.3-3.4.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from workbench.providers.llm.context import (
    LLMCallContext,
    current_llm_call_context,
)

logger = logging.getLogger(__name__)


def _serialize_response(resp: Any) -> dict | None:
    """Best-effort JSON-safe dump of an SDK response; never raises.

    Anthropic SDK responses are pydantic models, so ``model_dump(mode="json")``
    yields content blocks, stop_reason and usage. Anything without a usable
    ``model_dump`` (e.g. a test stub or a future SDK shape) yields ``None`` so a
    serialization quirk can never break a successful LLM call.
    """
    dump = getattr(resp, "model_dump", None)
    if not callable(dump):
        return None
    try:
        result = dump(mode="json")
    except Exception:
        try:
            result = dump()
        except Exception:
            return None
    return result if isinstance(result, dict) else None


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
    context: LLMCallContext | None = None
    system_prompt: str | None = None
    input_prompt: str | None = None
    completion: str | None = None
    structured: dict | None = None
    subcalls: list[dict] | None = None
    temperature: float | None = None
    tokens_estimated: bool = False
    is_fallback: bool = False
    raw_request: dict | None = None
    raw_response: dict | None = None


PlugboardSink = Callable[[PlugboardCallRecord], None]


async def record_plugboard_call(
    *,
    client: str,
    model: str,
    do_call: Callable[[], Awaitable[Any]],
    sink: PlugboardSink | None,
    item_count: int = 1,
    system_prompt: str | None = None,
    input_prompt: str | None = None,
    result_extractor: Callable[[Any], tuple[Any, Any, Any]] | None = None,
    temperature: float | None = None,
    is_fallback: bool = False,
    tokens_estimated: bool = False,
    raw_request: dict | None = None,
) -> Any:
    """Run ``do_call`` (one messages.create), emitting a PlugboardCallRecord.

    Counts each HTTP attempt (so retries inflate the call count, by design). On
    error, records the call + error_type with zero tokens, then re-raises.
    When ``sink`` is None this is a transparent pass-through.

    Optional provenance/body capture: ``system_prompt``, ``input_prompt``,
    ``temperature``, and ``is_fallback`` are attached verbatim, and the ambient
    :func:`current_llm_call_context` is recorded. On success, if
    ``result_extractor`` is given it is called with the response to derive
    ``(completion, structured, subcalls)``; a faulty extractor never breaks the
    LLM call (its failure leaves those fields ``None``).
    """
    start = time.monotonic()
    try:
        resp = await do_call()
    except Exception as e:
        if sink is not None:
            # Defense-in-depth: a raising sink must never alter the LLM call
            # result. Here the original exception MUST still propagate, so guard
            # the sink itself and only swallow the sink's own failure.
            try:
                sink(
                    PlugboardCallRecord(
                        client=client,
                        model=model,
                        latency_s=time.monotonic() - start,
                        error_type=type(e).__name__,
                        item_count=item_count,
                        context=current_llm_call_context(),
                        system_prompt=system_prompt,
                        input_prompt=input_prompt,
                        raw_request=raw_request,
                        temperature=temperature,
                        is_fallback=is_fallback,
                    )
                )
            except Exception:
                logger.exception("plugboard sink raised on error path; ignoring")
        raise
    if sink is not None:
        usage = getattr(resp, "usage", None)
        completion = None
        structured = None
        subcalls = None
        if result_extractor is not None:
            try:
                completion, structured, subcalls = result_extractor(resp)
            except Exception:
                completion = None
                structured = None
                subcalls = None
        # Defense-in-depth: a raising sink must never break a SUCCESSFUL call.
        # Guard the sink so the response is still returned even if it raises.
        try:
            raw_response = _serialize_response(resp)
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
                    context=current_llm_call_context(),
                    system_prompt=system_prompt,
                    input_prompt=input_prompt,
                    raw_request=raw_request,
                    raw_response=raw_response,
                    completion=completion,
                    structured=structured,
                    subcalls=subcalls,
                    temperature=temperature,
                    is_fallback=is_fallback,
                    tokens_estimated=tokens_estimated,
                )
            )
        except Exception:
            logger.exception("plugboard sink raised on success path; ignoring")
    return resp
