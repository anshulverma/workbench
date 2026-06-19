"""When a queued card is sent, the scheduler persists a Message and links it to
the card's item path via entity_item_links (entity_type='message')."""

import pytest

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.pipeline.scheduler import WorkbenchScheduler

pytestmark = pytest.mark.asyncio


async def test_capture_card_message_persists_and_links(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t",
            source_id="r1",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores

    msg = await sched._capture_message(
        kind="card",
        direction="outbound",
        bot_message_id="bot-99",
        body="What would you like to do?",
        summary="card for #" + root.path,
        item_path=root.path,
    )
    assert msg.id is not None
    got = await stores.messages.get_by_id(msg.id)
    assert got.bot_message_id == "bot-99"
    links = await stores.entity_links.for_entity("message", msg.id)
    assert {l.item_path for l in links} == {root.path}


async def test_capture_message_without_path_links_nothing(stores):
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    msg = await sched._capture_message(
        kind="alert",
        direction="outbound",
        bot_message_id="b",
        body="x",
        summary="s",
        item_path=None,
    )
    assert msg.id is not None
    assert await stores.entity_links.for_entity("message", msg.id) == []
