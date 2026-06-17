"""Full-fidelity LLM capture for the memory subservice.

The memory subservice's LLM calls are owned by Graphiti (via a wrapped
``AnthropicClient``). This module provides three graphiti-agnostic pieces so the
whole thing is unit-testable without importing ``graphiti_core``:

1. ``extract_messages`` / ``extract_completion_text`` — defensive extraction of
   the system/input prompt and completion text from whatever Graphiti hands the
   wrapped ``generate_response`` (Message objects or plain dicts).
2. ``build_memory_row`` — maps captured prompt/completion/tokens to a dict that
   matches the workbench-owned ``llm_calls`` column contract (migration 013),
   tagged ``origin="memory_subservice"``, ``stage="memory"``.
3. ``LlmCallWriter`` — an INSERT-only, best-effort, off-by-default cross-DB
   writer that inserts rows into the WORKBENCH ``llm_calls`` table using the
   memory process's own asyncpg pool (connected to a configured workbench DSN).
   It runs a one-time table-presence preflight; if disabled, pool-less, or the
   table is absent, capture is silently inert. Per-call DB failures are logged
   and dropped — they NEVER break a memory ingestion (ADR 0059).

See ADR 0059 and the "Memory Subservice Capture" section of the LLM usage
tracking design doc.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

ORIGIN = "memory_subservice"
STAGE = "memory"
PURPOSE = "memory"

# The exact column list written by PgLlmCallStore.save_many (migration 013),
# excluding the DB-managed id / created_at. The memory writer is pinned to this
# documented contract (ADR 0059). Order matches the INSERT below.
LLM_CALLS_COLUMNS = (
    "started_at",
    "origin",
    "purpose",
    "stage",
    "model",
    "temperature",
    "status",
    "error_type",
    "batch",
    "items",
    "tokens_in",
    "tokens_out",
    "cache_read_tokens",
    "cache_write_tokens",
    "latency_ms",
    "system_prompt",
    "subcalls",
    "tokens_estimated",
    "is_fallback",
)

_INSERT_SQL = (
    "INSERT INTO llm_calls "
    "(started_at,origin,purpose,stage,model,temperature,status,error_type,"
    "batch,items,tokens_in,tokens_out,cache_read_tokens,cache_write_tokens,"
    "latency_ms,system_prompt,subcalls,tokens_estimated,is_fallback) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,"
    "$17::jsonb,$18,$19)"
)


def _content_to_text(content: Any) -> str:
    """Coerce a message ``content`` field to text.

    Anthropic content can be a plain string or a list of content blocks
    (dicts with a ``text`` field). Be defensive about both.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(getattr(block, "text", block)))
        return "\n".join(parts)
    return str(content)


def extract_messages(messages: Any) -> tuple[str | None, str | None]:
    """Extract (system_prompt, input_prompt) from a Graphiti messages list.

    Handles both ``Message``-like objects (``.role`` / ``.content``) and plain
    dicts (``{"role", "content"}``). System messages become ``system_prompt``;
    all non-system messages are joined into ``input_prompt``. Returns
    ``(None, None)`` if nothing usable is found (never raises).
    """
    try:
        if not messages:
            return None, None
        system_parts: list[str] = []
        input_parts: list[str] = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content")
            else:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", None)
            text = _content_to_text(content)
            if role == "system":
                system_parts.append(text)
            else:
                input_parts.append(text)
        system_prompt = "\n".join(p for p in system_parts if p) or None
        input_prompt = "\n".join(p for p in input_parts if p) or None
        return system_prompt, input_prompt
    except Exception:  # capture must never break the call
        logger.debug("llm_capture: failed to extract messages", exc_info=True)
        return None, None


def extract_completion_text(result: Any) -> str | None:
    """Best-effort completion text from Graphiti's parsed result.

    Graphiti's ``generate_response`` typically returns a parsed dict; we
    serialize dicts/lists to JSON and pass strings through. Returns ``None``
    when there is nothing to capture.
    """
    if result is None:
        return None
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception:
        return str(result)


def build_memory_row(
    *,
    started_at: datetime,
    model: str,
    latency_ms: int | None,
    status: str,
    system_prompt: str | None,
    input_prompt: str | None,
    completion: str | None,
    structured: dict | None,
    tokens_in: int,
    tokens_out: int,
    tokens_available: bool,
    error_type: str | None = None,
) -> dict[str, Any]:
    """Build an ``llm_calls`` row dict for a single memory-subservice LLM call.

    Tokens are best-effort: when Graphiti does not surface usage
    (``tokens_available=False``) the counts stay 0 and ``tokens_estimated`` is
    set True. A subcall carrying the prompt/completion body is emitted whenever
    any body text was captured; otherwise ``subcalls`` is empty.
    """
    has_body = bool(input_prompt or completion or structured)
    subcalls: list[dict[str, Any]] = []
    if has_body:
        subcalls.append(
            {
                "item": "",
                "prompt": input_prompt or "",
                "completion": completion or "",
                "structured": structured,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        )

    return {
        "started_at": started_at,
        "origin": ORIGIN,
        "purpose": PURPOSE,
        "stage": STAGE,
        "model": model,
        "temperature": None,
        "status": status,
        "error_type": error_type,
        "batch": 1,
        "items": [],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": latency_ms,
        "system_prompt": system_prompt,
        "subcalls": subcalls,
        "tokens_estimated": not tokens_available,
        "is_fallback": False,
    }


class LlmCallWriter:
    """INSERT-only, best-effort writer into the workbench ``llm_calls`` table.

    Off by default. ``preflight()`` must succeed (flag enabled, pool present,
    ``to_regclass('llm_calls')`` non-null) before ``write()`` does anything.
    """

    def __init__(self, pool: Any, enabled: bool):
        self._pool = pool
        self._enabled = enabled
        self._active = False
        self._warned = False

    @property
    def active(self) -> bool:
        return self._active

    async def preflight(self) -> None:
        """One-time gate: enable capture only if flag on + table present."""
        self._active = False
        if not self._enabled:
            logger.info("llm_capture: disabled (llm_tracking_enabled is false)")
            return
        if self._pool is None:
            logger.warning(
                "llm_capture: enabled but workbench_dsn is unset; "
                "capture into llm_calls disabled"
            )
            return
        try:
            async with self._pool.acquire() as conn:
                regclass = await conn.fetchval("SELECT to_regclass('llm_calls')")
        except Exception as e:
            logger.warning(
                "llm_capture: preflight failed (%s); capture into llm_calls "
                "disabled",
                e,
            )
            return
        if regclass is None:
            logger.warning(
                "llm_capture: workbench llm_calls table is absent; capture "
                "disabled (apply migration 013 before enabling)"
            )
            return
        self._active = True
        logger.info("llm_capture: active (writing to workbench llm_calls)")

    async def write(self, row: dict[str, Any]) -> None:
        """Best-effort INSERT of one row. Never raises (logs + drops on error)."""
        if not self._active or self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    _INSERT_SQL,
                    row["started_at"],
                    row["origin"],
                    row["purpose"],
                    row["stage"],
                    row["model"],
                    row["temperature"],
                    row["status"],
                    row["error_type"],
                    row["batch"],
                    json.dumps(row["items"]),
                    row["tokens_in"],
                    row["tokens_out"],
                    row["cache_read_tokens"],
                    row["cache_write_tokens"],
                    row["latency_ms"],
                    row["system_prompt"],
                    json.dumps(row["subcalls"]),
                    row["tokens_estimated"],
                    row["is_fallback"],
                )
        except Exception as e:
            # Best-effort: a tracking failure must never break memory ingestion.
            if not self._warned:
                logger.warning("llm_capture: write to llm_calls failed: %s", e)
                self._warned = True
            else:
                logger.debug("llm_capture: write to llm_calls failed: %s", e)
