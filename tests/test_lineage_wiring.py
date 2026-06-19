"""stores.entity_links / stores.messages are constructed, the sink copies
correlation_id onto the record, and _drain_once passes entity_links into
save_many."""

import asyncio
import pytest
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import LLMCallContext
from workbench.providers.llm.plugboard import PlugboardCallRecord
from workbench.runtime.app import _to_llm_record, _drain_once

pytestmark = pytest.mark.asyncio


async def test_stores_construct_entity_links_and_messages(stores):
    assert stores.entity_links is not None
    assert stores.messages is not None


def test_to_llm_record_copies_correlation_id():
    rec = PlugboardCallRecord(
        client="plugboard",
        model="m",
        context=LLMCallContext(
            origin="filter",
            purpose="score_relevance",
            stage="filter",
            correlation_id="corr-9",
        ),
    )
    out = _to_llm_record(rec)
    assert out.correlation_id == "corr-9"


async def test_drain_once_passes_entity_links_to_save_many():
    q = asyncio.Queue()
    rec = MagicMock()
    await q.put(rec)
    store = MagicMock()
    store.save_many = AsyncMock()
    links = object()
    await _drain_once(q, store, entity_links=links, max_batch=10)
    store.save_many.assert_awaited_once()
    _, kwargs = store.save_many.call_args
    assert kwargs["entity_links"] is links
