from unittest.mock import AsyncMock, MagicMock

from workbench.config import AppConfig, ServerConfig, StorageConfig
from workbench.pipeline.scheduler import WorkbenchScheduler


def _sched():
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x/y"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "k"},
        server=ServerConfig(api_token="t"),
    )
    return WorkbenchScheduler(
        AsyncMock(), AsyncMock(), AsyncMock(), None, config, sources=[], llm=AsyncMock()
    )


def test_shutdown_flags_and_clears_debounce():
    sched = _sched()
    assert sched._debounce.pending_count == 0
    sched.shutdown()
    assert sched._shutting_down is True
    assert sched._debounce.pending_count == 0


def test_shutdown_calls_cancel_all():
    sched = _sched()
    sched._debounce = MagicMock()
    sched.shutdown()
    sched._debounce.cancel_all.assert_called_once()
