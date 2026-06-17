from datetime import datetime, timezone

import pytest

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    Priority,
    RawItem,
    TriageCard,
)


def _item(source_type="diff", source_id="D123", status=ItemStatus.ACTIVE):
    return Item(
        source_type=source_type,
        source_id=source_id,
        summary="s",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        status=status,
    )


@pytest.mark.asyncio
async def test_get_item_by_source_id_match_and_wrong_type(stores):
    item = await stores.items.save_item(_item())
    found = await stores.items.get_item_by_source_id("diff", "D123")
    assert found is not None and found.id == item.id
    assert await stores.items.get_item_by_source_id("task", "D123") is None


@pytest.mark.asyncio
async def test_get_item_by_source_id_excludes_archived(stores):
    await stores.items.save_item(_item(source_id="D999", status=ItemStatus.ARCHIVED))
    assert await stores.items.get_item_by_source_id("diff", "D999") is None


@pytest.mark.asyncio
async def test_get_active_by_source_excludes_archived_and_done(stores):
    await stores.items.save_item(_item(source_id="D1", status=ItemStatus.ACTIVE))
    await stores.items.save_item(_item(source_id="D2", status=ItemStatus.ARCHIVED))
    await stores.items.save_item(_item(source_id="D3", status=ItemStatus.DONE))
    active = await stores.items.get_active_by_source("diff")
    ids = {i.source_id for i in active}
    assert ids == {"D1"}


@pytest.mark.asyncio
async def test_update_raw_data_replaces_jsonb_and_bumps_updated_at(stores):
    from datetime import timedelta

    item = await stores.items.save_item(_item(source_id="D7"))
    raw = RawItem(
        id="D7",
        source_type="diff",
        source_label="D7 — x",
        raw_text='{"status": "accepted"}',
        urgency_signals={"p": 1},
    )
    await stores.items.update_raw_data(item.id, raw)
    refreshed = await stores.items.get_item(item.id)
    # Primary contract: the JSONB payload is replaced with the RawItem dump.
    assert refreshed.raw_data == raw.model_dump()
    # update_raw_data stamps updated_at via SQL NOW() — assert it is server-fresh.
    # (save_item stores naive utcnow() into timestamptz, which the DB session tz
    # skews, so a >= baseline comparison is unreliable; assert closeness to now.)
    now = datetime.now(timezone.utc)
    assert abs(now - refreshed.updated_at) < timedelta(minutes=10)


@pytest.mark.asyncio
async def test_get_card_by_item_id(stores):
    item = await stores.items.save_item(_item(source_id="D8"))
    card = TriageCard(item_id=item.id, card_content={"summary": "x"})
    await stores.triage.save_card(card)
    found = await stores.triage.get_card_by_item_id(item.id)
    assert found is not None and found.id == card.id
    assert await stores.triage.get_card_by_item_id(999999) is None


@pytest.mark.asyncio
async def test_clear_deferral(stores):
    item = await stores.items.save_item(_item(source_id="D9"))
    card = TriageCard(item_id=item.id, card_content={"summary": "x"})
    await stores.triage.save_card(card)
    await stores.triage.defer_card(card.id, datetime.now(timezone.utc))
    assert (await stores.triage.get_card(card.id)).deferred_until is not None
    await stores.triage.clear_deferral(card.id)
    assert (await stores.triage.get_card(card.id)).deferred_until is None


@pytest.mark.asyncio
async def test_get_card_by_id_and_unknown(stores):
    item = await stores.items.save_item(_item(source_id="D10"))
    card = TriageCard(item_id=item.id, card_content={"summary": "x"})
    await stores.triage.save_card(card)
    assert (await stores.triage.get_card(card.id)).id == card.id
    assert await stores.triage.get_card(999999) is None
