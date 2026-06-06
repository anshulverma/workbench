from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field, model_validator


class ServerConfig(BaseModel):
    port: int = 8421
    debug: bool = False
    api_token: str = "dev-token-change-me"


class StorageConfig(BaseModel):
    postgres_dsn: str


class QueueConfig(BaseModel):
    scorer: dict = Field(default_factory=dict)
    worker_concurrency: int = 2
    max_attempts: int = 3
    base_delay_seconds: int = 5


class TriageConfig(BaseModel):
    daily_cap: int = 20
    expiry_days: int = 7
    timeout_minutes: int = 30
    triage_poll_interval_seconds: float = 0.5


class PipelineConfig(BaseModel):
    include_threshold: int = 70
    drop_threshold: int = 30
    confidence_threshold: int = 70


class LoggingConfig(BaseModel):
    format: str = "json"  # "json" | "console"
    level: str = "INFO"
    log_dir: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    max_age_days: int = 84
    timezone: str = "America/Los_Angeles"


class MetricsConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "/metrics"


class DebugConfig(BaseModel):
    sql_queries: bool = False
    llm_prompts: bool = False
    llm_token_usage: bool = True
    request_bodies: bool = False
    enrichment_details: bool = False
    adapter_raw_items: bool = False


class PrivacyConfig(BaseModel):
    sanitize_logs: bool = True
    redact_emails: bool = True
    redact_phones: bool = True
    max_content_in_logs: int = 200
    allow_pii_in_debug_logs: bool = False


class TracingConfig(BaseModel):
    enabled: bool = False
    exporter: str = "console"
    otlp_endpoint: str | None = None
    sample_rate: float = 1.0


class RetentionConfig(BaseModel):
    archived_items_days: int = 90
    done_items_days: int = 90
    expired_cards_days: int = 30
    responded_cards_days: int = 90
    enrichment_traces_days: int = 30
    dead_letters_days: int = 30


class AlertConditions(BaseModel):
    dead_letter_threshold: int = 3
    adapter_failure_threshold: int = 3
    queue_depth_threshold: int = 50
    stale_card_days: int = 3
    llm_failure_threshold: int = 2


class AlertConfig(BaseModel):
    enabled: bool = True
    cooldown_minutes: int = 60
    conditions: AlertConditions = Field(default_factory=AlertConditions)


class SchedulerConfig(BaseModel):
    poll_interval_minutes: int = 15
    morning_briefing_hour: int = 9


class EnrichmentConfig(BaseModel):
    providers: list[dict] = Field(default_factory=list)
    default: dict = Field(
        default_factory=lambda: {
            "class": "workbench.providers.enrichment.stub.StubEnricher"
        }
    )


class AppConfig(BaseModel):
    version: str = "0.3.0"
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig
    llm: dict
    queue: QueueConfig = Field(default_factory=QueueConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    messenger: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    memory: dict | None = None
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    alerting: AlertConfig = Field(default_factory=AlertConfig)
    connections: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_enrichment(cls, values):
        enrichment = values.get("enrichment")
        if isinstance(enrichment, dict) and "class" in enrichment:
            values["enrichment"] = {"providers": [], "default": enrichment}
        return values


def load_config(config_path: str, override_path: str | None = None) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print("Run 'cp config.example.yml config.yml' and edit it.", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)

    config = AppConfig(**resolved)

    major = int(config.version.split(".")[0])
    expected_major = 0
    if major != expected_major:
        print(
            f"Error: Config version {config.version} is incompatible (expected major {expected_major})",
            file=sys.stderr,
        )
        sys.exit(1)

    return config


def load_config_from_string(yaml_str: str) -> AppConfig:
    raw = OmegaConf.create(yaml_str)
    resolved = OmegaConf.to_container(raw, resolve=True)
    return AppConfig(**resolved)
