# tests/test_llm_calls_retention.py

import pytest
from unittest.mock import MagicMock, AsyncMock
from workbench.pipeline.scheduler import run_retention_cleanup
from workbench.config.models import RetentionConfig

pytestmark = pytest.mark.asyncio


def _stores():
    """Create a mock stores object with all retention methods."""
    s = MagicMock()
    # Existing retention methods
    s.items.delete_older_than = AsyncMock(return_value=0)
    s.triage.delete_older_than = AsyncMock(return_value=0)
    s.enrichment.delete_older_than = AsyncMock(return_value=0)
    s.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)
    s.ingestion_runs.delete_older_than = AsyncMock(return_value=0)
    # New llm_calls retention methods
    s.llm_calls.delete_older_than = AsyncMock(return_value=5)
    s.llm_calls.prune_to_max_rows = AsyncMock(return_value=2)
    return s


async def test_llm_calls_swept_by_days():
    """Verify llm_calls.delete_older_than is called with config.llm_calls_days."""
    s = _stores()
    config = RetentionConfig()  # llm_calls_days=28, llm_calls_max_rows=None
    result = await run_retention_cleanup(s, config)
    s.llm_calls.delete_older_than.assert_awaited_once_with(28)
    assert result["llm_calls"] == 5
    s.llm_calls.prune_to_max_rows.assert_not_awaited()  # None → no prune


async def test_llm_calls_row_cap_prunes_when_set():
    """Verify llm_calls.prune_to_max_rows is called when llm_calls_max_rows is set."""
    s = _stores()
    config = RetentionConfig(llm_calls_max_rows=1000)
    result = await run_retention_cleanup(s, config)
    s.llm_calls.prune_to_max_rows.assert_awaited_once_with(1000)
    assert result["llm_calls_pruned"] == 2


async def test_llm_calls_skipped_when_store_none():
    """Verify llm_calls retention is skipped safely when the store is None."""
    s = _stores()
    s.llm_calls = None
    config = RetentionConfig()
    result = await run_retention_cleanup(s, config)  # must not raise
    assert "llm_calls" not in result or result.get("llm_calls") == 0
