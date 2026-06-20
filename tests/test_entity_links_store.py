"""PgEntityLinkStore: in-DB path resolution, idempotency, correlation rows,
subtree scans, unlink, and reverse lookups."""

import pytest

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.storage.postgres.entity_links import PgEntityLinkStore

pytestmark = pytest.mark.asyncio


async def _make_tree(stores):
    """Build root #N with two children #N.1, #N.2. Returns the three Items."""
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.EXTRACTED,
        )
    )
    c1 = await stores.items.allocate_child(
        root,
        Item(
            source_type="t",
            source_id="r1",
            summary="c1",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        ),
    )
    c2 = await stores.items.allocate_child(
        root,
        Item(
            source_type="t",
            source_id="r1",
            summary="c2",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        ),
    )
    return root, c1, c2


async def test_record_resolves_paths_to_ids(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 991, [root.path, c1.path])
    links = await els.for_entity("llm_call", 991)
    by_path = {l.item_path: l for l in links}
    assert set(by_path) == {root.path, c1.path}
    assert by_path[root.path].item_id == root.id
    assert by_path[c1.path].item_id == c1.id


async def test_record_is_idempotent(stores, pg_pool):
    root, _, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path])
    await els.record("llm_call", 1, [root.path])
    assert len(await els.for_entity("llm_call", 1)) == 1


async def test_record_unknown_path_writes_no_row(stores, pg_pool):
    root, _, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path, "999999"])
    links = await els.for_entity("llm_call", 1)
    assert {l.item_path for l in links} == {root.path}


async def test_record_empty_is_noop(stores, pg_pool):
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [])
    assert await els.for_entity("llm_call", 1) == []


async def test_record_by_correlation_leaves_entity_id_null(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    rows = await els.for_item(c1.path)
    assert len(rows) == 1
    assert rows[0].entity_id is None
    assert rows[0].correlation_id == "corr-1"


async def test_record_by_correlation_idempotent(stores, pg_pool):
    _, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    assert len(await els.for_item(c1.path)) == 1


async def test_for_item_subtree(stores, pg_pool):
    root, c1, c2 = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path])
    await els.record("llm_call", 2, [c1.path])
    await els.record("llm_call", 3, [c2.path])
    shallow = await els.for_item(root.path, subtree=False)
    assert {l.item_path for l in shallow} == {root.path}
    deep = await els.for_item(root.path, subtree=True)
    assert {l.item_path for l in deep} == {root.path, c1.path, c2.path}


async def test_unlink_entity_deletes_rows(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 7, [root.path, c1.path])
    n = await els.unlink_entity("llm_call", 7)
    assert n == 2
    assert await els.for_entity("llm_call", 7) == []
