from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    port: int = 8422


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j"


class StorageConfig(BaseModel):
    postgres_dsn: str = "postgres://memory:memory@localhost:5432/memory"


class LLMConfig(BaseModel):
    client_class: str = "memory.llm.DefaultLLMClient"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-haiku-4-5-20251001"


class EmbedderConfig(BaseModel):
    embedder_class: str = "memory.embedder.OpenAIEmbedderWrapper"
    cross_encoder_class: str = ""
    api_key: str = ""
    model: str = "text-embedding-3-small"
    embedding_dim: int = 1536


class QueueConfig(BaseModel):
    max_attempts: int = 3
    base_delay_seconds: int = 5
    worker_concurrency: int = 1


class LoggingConfig(BaseModel):
    level: str = "INFO"
    timezone: str = "America/Los_Angeles"
    log_dir: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 10


class MetricsConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "/metrics"
    summary_log: bool = True
    summary_interval_seconds: int = 30


class MemoryConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


def load_config(config_path: str, override_path: str | None = None) -> MemoryConfig:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)
    return MemoryConfig(**resolved)
