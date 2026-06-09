from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "SourceRelevanceConfig",
    "SourceConfig",
    "SourceConfigUpdate",
]


class SourceRelevanceConfig(BaseModel):
    """Per-source relevance/noise thresholds (ADR0044, spec §11).

    Partitions LLM-scored items into auto-include vs triage vs drop. Scores are
    integers 0..100 (matching ``LLMProvider.score_relevance``); a value of
    ``None`` for the whole object means "inherit the global PipelineConfig
    thresholds" so existing sources keep their current routing.

    Routing (per ``filter.decide_from_score``):
      * relevance >= ``auto_include_threshold`` -> auto-include
      * relevance <  ``drop_below``             -> drop as noise
      * otherwise                               -> send to triage

    ``triage_threshold`` is the lower edge of the triage band; it is surfaced
    for the UI's three-slider Noise Filter and validated to sit between
    ``drop_below`` and ``auto_include_threshold``. The two routing-controlling
    knobs are ``auto_include_threshold`` and ``drop_below``.
    """

    auto_include_threshold: int = Field(default=70, ge=0, le=100)
    triage_threshold: int = Field(default=30, ge=0, le=100)
    drop_below: int = Field(default=30, ge=0, le=100)

    @model_validator(mode="after")
    def _check_ordering(self) -> "SourceRelevanceConfig":
        if self.drop_below > self.auto_include_threshold:
            raise ValueError(
                "drop_below must be <= auto_include_threshold "
                f"({self.drop_below} > {self.auto_include_threshold})"
            )
        if not (
            self.drop_below <= self.triage_threshold <= self.auto_include_threshold
        ):
            raise ValueError(
                "triage_threshold must lie within "
                "[drop_below, auto_include_threshold]"
            )
        return self


class SourceConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    adapter_type: str
    config: dict = Field(default_factory=dict)
    schedule: str = "*/15 * * * *"
    enabled: bool = True
    relevance: SourceRelevanceConfig | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SourceConfigUpdate(BaseModel):
    config: dict | None = None
    schedule: str | None = None
    enabled: bool | None = None
    adapter_type: str | None = None
    connection: str | None = None
    relevance: SourceRelevanceConfig | None = None
