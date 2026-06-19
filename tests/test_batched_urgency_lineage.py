"""_enqueue_with_urgency stamps a correlation_id on the batched score_urgency_many
call and, after enqueue births the roots, records the roots by correlation_id."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem

pytestmark = pytest.mark.asyncio


async def _scheduler(stores):
    from workbench.pipeline.scheduler import WorkbenchScheduler

    # Build a minimal config with batching enabled.
    config = MagicMock()
    config.batching.enabled = True
    config.batching.score_urgency = True
    config.batching.max_batch_size = 20

    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    sched.config = config
    sched.pipeline = MagicMock()
    return sched


async def test_batched_urgency_records_roots_by_correlation(stores):
    captured = {}

    scorer = MagicMock()

    async def fake_score_many(pairs, max_batch_size):
        captured["ctx"] = current_llm_call_context()
        return [60] * len(pairs)

    scorer.score_urgency_many = fake_score_many

    sched = await _scheduler(stores)
    sched.pipeline.queue_scorer = scorer

    # enqueue births a root per item; return (job, root_path).
    minted = {"r1": "501", "r2": "502"}

    async def fake_enqueue(
        raw_text,
        source_type,
        *,
        source_id,
        urgency_signals,
        trigger,
        urgency_score,
        source_ref,
        source_url,
    ):
        return (MagicMock(), minted[source_id])

    sched.pipeline.enqueue = fake_enqueue

    items = [
        (
            RawItem(
                id="r1",
                source_type="t",
                source_label="",
                raw_text="a",
                urgency_signals={"k": 1},
            ),
            "r1",
        ),
        (
            RawItem(
                id="r2",
                source_type="t",
                source_label="",
                raw_text="b",
                urgency_signals={"k": 2},
            ),
            "r2",
        ),
    ]

    # Pre-create the roots at the minted paths so record_by_correlation resolves them.
    from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus

    for sid, path in minted.items():
        await stores.items.pool.execute(
            "INSERT INTO items (source_type, source_id, summary, category, origin, "
            "priority, status, path) VALUES ('t',$1,'r','informational',"
            "'auto_included','P2','ingested',$2)",
            sid,
            path,
        )

    from workbench.domain.pipeline import JobTrigger

    await sched._enqueue_with_urgency(items, JobTrigger.MANUAL)

    corr = captured["ctx"].correlation_id
    assert corr is not None
    rows_501 = await stores.entity_links.for_item("501")
    rows_502 = await stores.entity_links.for_item("502")
    assert any(r.correlation_id == corr for r in rows_501)
    assert any(r.correlation_id == corr for r in rows_502)
