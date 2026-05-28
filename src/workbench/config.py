from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field


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


class PipelineConfig(BaseModel):
    include_threshold: int = 70
    drop_threshold: int = 30
    confidence_threshold: int = 70


class SchedulerConfig(BaseModel):
    poll_interval_minutes: int = 15
    morning_briefing_hour: int = 9


class AppConfig(BaseModel):
    version: str = "0.1.0"
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig
    llm: dict
    queue: QueueConfig = Field(default_factory=QueueConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    messenger: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    enrichment: dict | None = None
    memory: dict | None = None


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
        print(f"Error: Config version {config.version} is incompatible (expected major {expected_major})", file=sys.stderr)
        sys.exit(1)

    return config
