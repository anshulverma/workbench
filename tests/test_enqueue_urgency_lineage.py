"""enqueue stamps item_paths=(root.path,) on the per-item score_urgency call and
returns the minted root path alongside the job (so the scheduler can link the
batched urgency call by correlation_id later)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.pipeline.engine import PipelineEngine

pytestmark = pytest.mark.asyncio


async def test_enqueue_returns_root_path(stores):
    eng = PipelineEngine(stores, AsyncMock(), MagicMock(), AsyncMock())
    job, root_path = await eng.enqueue("hello world raw text", "t", source_id="s1")
    assert root_path is not None
    root = await stores.items.get_by_path(root_path)
    assert root is not None and root.source_id == "s1"


async def test_enqueue_per_item_urgency_stamps_root_path(stores):
    captured = {}

    scorer = MagicMock()

    async def fake_score_urgency(raw_text, signals):
        captured["ctx"] = current_llm_call_context()
        return 70

    scorer.score_urgency = fake_score_urgency

    eng = PipelineEngine(
        stores, AsyncMock(), MagicMock(), AsyncMock(), queue_scorer=scorer
    )
    job, root_path = await eng.enqueue(
        "hello world raw text", "t", source_id="s2", urgency_signals={"k": "v"}
    )
    assert captured["ctx"].item_paths == (root_path,)
