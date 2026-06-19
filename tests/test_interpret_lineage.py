"""The free-text interpret_triage_response call stamps the card's item path, and
the resulting InteractionEntry is linked via entity_item_links at that path.

This test drives the small helper extracted in Task 14:
scheduler._interpret_item_path(card) -> str | None resolves the card's item_id to
its path; and _record_interaction_link(entry_id, path) writes the link.
"""

import pytest
from unittest.mock import MagicMock

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.pipeline.scheduler import WorkbenchScheduler

pytestmark = pytest.mark.asyncio


async def test_interpret_item_path_resolves_card_item(stores):
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
    card = MagicMock()
    card.item_id = root.id
    path = await sched._interpret_item_path(card)
    assert path == root.path

    card_no_item = MagicMock()
    card_no_item.item_id = None
    assert await sched._interpret_item_path(card_no_item) is None


async def test_record_interaction_link_writes_row(stores):
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
    await sched._record_interaction_link(55, root.path)
    rows = await stores.entity_links.for_entity("interaction", 55)
    assert {r.item_path for r in rows} == {root.path}
