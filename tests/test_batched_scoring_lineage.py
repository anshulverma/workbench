"""Batched relevance scoring stamps a correlation_id on the score_relevance_many
call (NOT the root path), and after children are allocated the engine calls
record_by_correlation for the depth-1 child paths (regression for the
mis-stamped-root bug)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
    RawItem,
    JobStatus,
    JobTrigger,
    PipelineJob,
)
from workbench.pipeline.engine import PipelineEngine

pytestmark = pytest.mark.asyncio


async def test_batched_scoring_uses_correlation_and_records_children(stores):
    # Root born like enqueue would.
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.INGESTED,
        )
    )

    captured = {}

    async def fake_score_many(ctx_for_scoring, max_batch_size):
        captured["ctx"] = current_llm_call_context()
        # two items -> both auto_include (high relevance, high confidence)
        return [(90, 90)] * len(ctx_for_scoring)

    llm = MagicMock()
    llm.score_relevance_many = fake_score_many

    memory = AsyncMock()
    memory.query_preferences = AsyncMock(return_value=[])
    memory.query_entity = AsyncMock(return_value=None)
    memory.query_relationships = AsyncMock(return_value=[])
    memory.record_pipeline_decision = AsyncMock()

    eng = PipelineEngine(
        stores,
        memory,
        llm,
        AsyncMock(),
        batch_relevance=True,
        max_batch_size=20,
    )

    raw = RawItem(id="r1", source_type="t", source_label="", raw_text="x" * 50)
    job = PipelineJob(
        trigger=JobTrigger.MANUAL, status=JobStatus.QUEUED, input_hash="h"
    )
    await stores.jobs.save_job(job)

    # Two extracted items -> two depth-1 children.
    llm_extract = [
        MagicMock(summary="c1", category=ItemCategory.INFORMATIONAL, source_context=""),
        MagicMock(summary="c2", category=ItemCategory.INFORMATIONAL, source_context=""),
    ]

    import workbench.pipeline.engine as engine_mod

    orig = engine_mod.extract_items

    async def fake_extract(llm, raw_text, source_type, *, root_path=None):
        return llm_extract

    engine_mod.extract_items = fake_extract
    try:
        await eng.process_raw_item(raw, job.id)
    finally:
        engine_mod.extract_items = orig

    # The batched call carried a correlation_id, not the root path.
    assert captured["ctx"].item_paths == ()
    assert captured["ctx"].correlation_id is not None

    # After allocation, link rows exist for the two children via correlation_id.
    rows = await stores.entity_links.for_item(root.path, subtree=True)
    child_paths = {
        r.item_path for r in rows if r.correlation_id == captured["ctx"].correlation_id
    }
    assert child_paths == {f"{root.path}.1", f"{root.path}.2"}
