"""save_many writes entity_item_links rows for call-time records (those with
items), persists correlation_id, and the retention pruners cascade-unlink."""

import pytest
from datetime import datetime, timezone, timedelta

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.domain.llm_calls import LlmCallRecord
from workbench.storage.postgres.entity_links import PgEntityLinkStore

pytestmark = pytest.mark.asyncio


async def _root(stores, source_id):
    return await stores.items.create_root(
        Item(
            source_type="t",
            source_id=source_id,
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.EXTRACTED,
        )
    )


def _rec(items=None, correlation_id=None, started=None):
    return LlmCallRecord(
        started_at=started or datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
        items=items or [],
        correlation_id=correlation_id,
    )


async def test_save_many_writes_links_for_call_time_records(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many([_rec(items=[root.path])], entity_links=els)
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(calls) == 1
    links = await els.for_entity("llm_call", calls[0].id)
    assert {l.item_path for l in links} == {root.path}


async def test_save_many_no_links_for_correlation_records(stores, pg_pool):
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many(
        [_rec(items=[], correlation_id="corr-1")], entity_links=els
    )
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(calls) == 1
    # correlation_id persisted on the row, but NO link rows written here.
    got = await stores.llm_calls.get_by_id(calls[0].id)
    assert got.correlation_id == "corr-1"
    assert await els.for_entity("llm_call", calls[0].id) == []


async def test_save_many_correlation_record_with_index_items_writes_no_links(
    stores, pg_pool
):
    """Regression: a batched/correlation record arrives with `items` holding
    batch INDEX strings ("0","1",...). Those indices can collide with real root
    paths (a root's path is str(id), e.g. "1"). save_many MUST skip call-time
    links for any record carrying a correlation_id so it never forges links to
    those unrelated roots."""
    # Create roots so that some have paths "1"/"2"/... that collide with indices.
    roots = [await _root(stores, f"r{n}") for n in range(3)]
    els = PgEntityLinkStore(pg_pool)
    # Indices that exist as real root paths plus a guaranteed-collision set.
    index_items = ["0", "1", "2"] + [r.path for r in roots]
    await stores.llm_calls.save_many(
        [_rec(items=index_items, correlation_id="corr-batch")],
        entity_links=els,
    )
    calls = await stores.llm_calls.list_calls(limit=10)
    corr_calls = [c for c in calls if c.correlation_id == "corr-batch"]
    assert len(corr_calls) == 1
    # No call-time links written for the correlation record, even though some
    # index strings collide with real root paths.
    assert await els.for_entity("llm_call", corr_calls[0].id) == []
    # And none of the real roots gained a spurious llm_call link.
    for r in roots:
        links = await els.for_item(r.path)
        assert [l for l in links if l.entity_type == "llm_call"] == []


async def test_to_llm_record_to_save_many_correlation_writes_no_links(stores, pg_pool):
    """Mirror the real sink path: a batched PlugboardCallRecord (correlation_id
    set, no context.item_paths, subcalls carrying index `item`s) flows through
    runtime/app.py `_to_llm_record` -> save_many and forges ZERO links."""
    from types import SimpleNamespace
    from workbench.runtime.app import _to_llm_record

    roots = [await _root(stores, f"r{n}") for n in range(2)]
    els = PgEntityLinkStore(pg_pool)
    # Transport view of a batched urgency call: context has a correlation_id but
    # NO item_paths, so _to_llm_record falls back to subcall index `item`s.
    ctx = SimpleNamespace(
        origin="queue_scorer",
        purpose="score_urgency",
        stage="scoring",
        item_paths=(),
        correlation_id="corr-sink",
    )
    rec = SimpleNamespace(
        context=ctx,
        latency_s=0.01,
        model="m",
        temperature=None,
        error_type=None,
        item_count=2,
        subcalls=[{"item": "0"}, {"item": "1"}],
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_write_tokens=0,
        system_prompt=None,
        tokens_estimated=False,
        is_fallback=False,
    )
    record = _to_llm_record(rec)
    assert record.correlation_id == "corr-sink"
    assert record.items == ["0", "1"]  # index fallback, not real paths
    await stores.llm_calls.save_many([record], entity_links=els)
    calls = await stores.llm_calls.list_calls(limit=10)
    sink_calls = [c for c in calls if c.correlation_id == "corr-sink"]
    assert len(sink_calls) == 1
    assert await els.for_entity("llm_call", sink_calls[0].id) == []
    for r in roots:
        links = await els.for_item(r.path)
        assert [l for l in links if l.entity_type == "llm_call"] == []


async def test_save_many_without_entity_links_still_persists(stores):
    root_paths = []
    await stores.llm_calls.save_many([_rec(items=root_paths)])
    assert len(await stores.llm_calls.list_calls(limit=10)) == 1


async def test_delete_older_than_unlinks(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many([_rec(items=[root.path])], entity_links=els)
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(await els.for_entity("llm_call", calls[0].id)) == 1
    # delete_older_than filters on created_at (server-default now(), not inserted
    # by save_many), so age that column directly to make the row eligible.
    await pg_pool.execute(
        "UPDATE llm_calls SET created_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=40),
        calls[0].id,
    )
    await stores.llm_calls.delete_older_than(28, entity_links=els)
    assert await els.for_entity("llm_call", calls[0].id) == []


async def test_prune_to_max_rows_unlinks(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many(
        [
            _rec(
                items=[root.path],
                started=datetime.now(timezone.utc) - timedelta(minutes=3),
            ),
            _rec(
                items=[root.path],
                started=datetime.now(timezone.utc) - timedelta(minutes=1),
            ),
        ],
        entity_links=els,
    )
    calls = await stores.llm_calls.list_calls(limit=10)
    oldest = calls[-1].id
    deleted = await stores.llm_calls.prune_to_max_rows(1, entity_links=els)
    assert deleted == 1
    assert await els.for_entity("llm_call", oldest) == []
