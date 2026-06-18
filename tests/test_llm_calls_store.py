import pytest
from datetime import datetime, timezone, timedelta
from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall

pytestmark = pytest.mark.asyncio


async def _rec(stage="filter", status="ok", batch=1, started=None):
    return LlmCallRecord(
        started_at=started or datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage=stage,
        model="m",
        status=status,
        batch=batch,
        items=["i1"],
        tokens_in=10,
        tokens_out=4,
        latency_ms=120,
        subcalls=[
            LlmSubcall(
                item="i1",
                prompt="p",
                completion="c",
                structured={"a": 1},
                tokens_in=10,
                tokens_out=4,
            )
        ],
    )


async def test_save_and_list(llm_calls_store):
    await llm_calls_store.save_many([await _rec(), await _rec(stage="triage")])
    rows = await llm_calls_store.list_calls(limit=10)
    assert len(rows) == 2
    got = await llm_calls_store.get_by_id(rows[0].id)
    assert got.subcalls[0].structured == {"a": 1}


async def test_metrics_24h(llm_calls_store):
    await llm_calls_store.save_many(
        [await _rec(status="ok"), await _rec(status="error"), await _rec(batch=3)]
    )
    m = await llm_calls_store.metrics_24h()
    assert m["calls_24h"] == 3
    assert 0 < m["error_rate"] < 1
    assert m["batched_pct"] > 0


async def test_delete_older_than(llm_calls_store):
    old = await _rec(started=datetime.now(timezone.utc) - timedelta(days=40))
    await llm_calls_store.save_many([old])
    assert isinstance(await llm_calls_store.delete_older_than(28), int)


async def test_list_filters_and_cursor(llm_calls_store):
    await llm_calls_store.save_many(
        [await _rec(stage="filter"), await _rec(stage="triage")]
    )
    only = await llm_calls_store.list_calls(limit=10, stage="triage")
    assert all(r.stage == "triage" for r in only)


async def test_count_since(llm_calls_store):
    await llm_calls_store.save_many([await _rec(), await _rec(stage="triage")])
    count = await llm_calls_store.count_since(
        datetime.now(timezone.utc) - timedelta(hours=1)
    )
    assert count == 2
    # Far-future time should return 0
    future_count = await llm_calls_store.count_since(
        datetime.now(timezone.utc) + timedelta(days=365)
    )
    assert future_count == 0


async def test_prune_to_max_rows(llm_calls_store):
    # Save 3 records with distinct timestamps
    await llm_calls_store.save_many(
        [
            await _rec(started=datetime.now(timezone.utc) - timedelta(minutes=3)),
            await _rec(started=datetime.now(timezone.utc) - timedelta(minutes=2)),
            await _rec(started=datetime.now(timezone.utc) - timedelta(minutes=1)),
        ]
    )
    # Prune to keep only 1 row
    deleted = await llm_calls_store.prune_to_max_rows(1)
    assert deleted == 2
    # Verify only 1 row remains (the most recent)
    remaining = await llm_calls_store.list_calls(limit=10)
    assert len(remaining) == 1
