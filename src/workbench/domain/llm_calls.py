"""LLM call domain models for usage tracking and analytics.

Design notes:
- `stage` and `status` use Literal (not Enum) because their values are the exact
  strings consumed by `/api/llm/*` JSON endpoints and the React UI — they are the
  API/UI contract, not persisted enum discriminators.
- `started_at` has no default by design — the caller supplies the actual
  call-start timestamp (UTC).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "LlmCallRecord",
    "LlmSubcall",
]


class LlmSubcall(BaseModel):
    item: str
    prompt: str
    completion: str
    structured: dict | None = None
    tokens_in: int
    tokens_out: int | None = None


class LlmCallRecord(BaseModel):
    id: int | None = None
    started_at: datetime
    origin: str
    purpose: str
    stage: Literal[
        "extract",
        "scoring",
        "filter",
        "triage",
        "aggregate",
        "enricher",
        "briefing",
        "memory",
    ]
    model: str
    temperature: float | None = None
    status: Literal["ok", "error"]
    error_type: str | None = None
    batch: int = 1
    items: list[str] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int | None = None
    system_prompt: str | None = None
    subcalls: list[LlmSubcall] = Field(default_factory=list)
    tokens_estimated: bool = False
    is_fallback: bool = False
