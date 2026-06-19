"""run_retention_cleanup passes stores.entity_links into the llm_calls pruners and
sweeps messages so message link rows do not dangle."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from workbench.pipeline.scheduler import run_retention_cleanup
from workbench.config.models import RetentionConfig

pytestmark = pytest.mark.asyncio


def _stores():
    s = MagicMock()
    s.items.delete_older_than = AsyncMock(return_value=0)
    s.triage.delete_older_than = AsyncMock(return_value=0)
    s.enrichment.delete_older_than = AsyncMock(return_value=0)
    s.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)
    s.ingestion_runs.delete_older_than = AsyncMock(return_value=0)
    s.llm_calls.delete_older_than = AsyncMock(return_value=0)
    s.llm_calls.prune_to_max_rows = AsyncMock(return_value=0)
    s.entity_links = MagicMock()
    s.messages = MagicMock()
    s.messages.delete_older_than = AsyncMock(return_value=3)
    return s


async def test_llm_calls_pruners_receive_entity_links():
    s = _stores()
    config = RetentionConfig(llm_calls_max_rows=1000)
    await run_retention_cleanup(s, config)
    _, kwargs = s.llm_calls.delete_older_than.call_args
    assert kwargs.get("entity_links") is s.entity_links
    _, kwargs2 = s.llm_calls.prune_to_max_rows.call_args
    assert kwargs2.get("entity_links") is s.entity_links


async def test_messages_swept():
    s = _stores()
    config = RetentionConfig()
    result = await run_retention_cleanup(s, config)
    s.messages.delete_older_than.assert_awaited_once()
    assert result.get("messages") == 3
