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
