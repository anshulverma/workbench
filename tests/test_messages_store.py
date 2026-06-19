"""PgMessageStore: save/get/list/delete round-trips for the durable messages
entity."""

import pytest
from datetime import datetime, timezone, timedelta

from workbench.domain.messages import Message
from workbench.storage.postgres.messages import PgMessageStore

pytestmark = pytest.mark.asyncio


async def test_save_assigns_id_and_get_roundtrips(pg_pool):
    ms = PgMessageStore(pg_pool)
    saved = await ms.save(
        Message(kind="card", direction="outbound", body="hello", summary="card #5")
    )
    assert saved.id is not None
    got = await ms.get_by_id(saved.id)
    assert got.kind == "card"
    assert got.direction == "outbound"
    assert got.body == "hello"
    assert got.summary == "card #5"


async def test_get_missing_returns_none(pg_pool):
    ms = PgMessageStore(pg_pool)
    assert await ms.get_by_id(999999) is None


async def test_list_recent_orders_newest_first(pg_pool):
    ms = PgMessageStore(pg_pool)
    a = await ms.save(Message(kind="alert", direction="outbound", summary="a"))
    b = await ms.save(Message(kind="card", direction="outbound", summary="b"))
    recent = await ms.list_recent(10)
    assert [m.id for m in recent[:2]] == [b.id, a.id]


async def test_delete_older_than(pg_pool):
    ms = PgMessageStore(pg_pool)
    saved = await ms.save(Message(kind="reply", direction="inbound", summary="r"))
    await pg_pool.execute(
        "UPDATE messages SET created_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=40),
        saved.id,
    )
    deleted = await ms.delete_older_than(28)
    assert deleted == 1
    assert await ms.get_by_id(saved.id) is None


async def test_delete_older_than_unlinks_message_links(stores, pg_pool):
    from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
    from workbench.storage.postgres.entity_links import PgEntityLinkStore

    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="m1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.EXTRACTED,
        )
    )
    ms = PgMessageStore(pg_pool)
    els = PgEntityLinkStore(pg_pool)
    saved = await ms.save(Message(kind="card", direction="outbound", summary="c"))
    await els.record("message", saved.id, [root.path])
    assert len(await els.for_entity("message", saved.id)) == 1

    await pg_pool.execute(
        "UPDATE messages SET created_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=40),
        saved.id,
    )
    deleted = await ms.delete_older_than(28, entity_links=els)
    assert deleted == 1
    assert await ms.get_by_id(saved.id) is None
    assert await els.for_entity("message", saved.id) == []
