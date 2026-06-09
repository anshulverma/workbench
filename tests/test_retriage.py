import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.domain import (
    TriageCard,
    TriageOption,
    CardMessage,
    RawItem,
    Item,
    ItemStatus,
    ItemCategory,
    ItemOrigin,
    Priority,
)
from workbench.providers.change_detector.base import ChangeResult
from workbench.pipeline.presenter import PlainCardPresenter
from workbench.pipeline.scheduler import WorkbenchScheduler


def _raw(diff_version="v1"):
    return RawItem(
        id="D123_t",
        source_type="diff",
        source_label="D123",
        raw_text=json.dumps(
            {"number": "D123", "status": "accepted", "diff_version": diff_version}
        ),
    )


def _result(change_type="status_changed", critical=False):
    return ChangeResult(
        is_material=True,
        is_terminal=False,
        is_critical=critical,
        changed_fields=["status"],
        change_type=change_type,
        reason="status changed",
    )


def _item():
    return Item(
        id="it1",
        source_type="diff",
        source_id="D123",
        summary="Review D123",
        category=ItemCategory.INFORMATIONAL,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        status=ItemStatus.ACTIVE,
        raw_data={"raw_text": json.dumps({"number": "D123", "status": "needs_review"})},
    )


def _sched(messenger):
    stores = MagicMock()
    stores.items.get_item = AsyncMock(return_value=_item())
    stores.triage.count_sent_today = AsyncMock(return_value=0)
    stores.triage.update_card = AsyncMock()
    stores.triage.save_card = AsyncMock()
    stores.triage.clear_deferral = AsyncMock()
    config = MagicMock()
    config.triage.daily_cap = 20
    config.logging.timezone = "UTC"
    config.alerting.enabled = False
    pipeline = MagicMock()
    pipeline.enricher = MagicMock()
    pipeline.triage_expiry_days = 7
    memory = AsyncMock()
    memory.is_available = AsyncMock(return_value=False)
    sched = WorkbenchScheduler(
        stores, memory, pipeline, messenger, config, llm=AsyncMock()
    )
    sched.llm.generate_triage_card = AsyncMock(
        return_value=TriageCard(
            card_content={
                "summary": "Review D123",
                "card_body": "Review D123",
                "source_type": "diff",
            },
            options=[TriageOption(label="Keep", action="skip")],
        )
    )
    sched.presenter = PlainCardPresenter()
    sched.content_generators = {}
    return sched, stores


def _sent_card():
    return TriageCard(
        id="c1",
        item_id="it1",
        status="sent",
        bot_message_id="spaces/A/messages/p1",
        card_content={
            "summary": "Review D123",
            "card_body": "Review D123",
            "source_type": "diff",
            "sections": {
                "hunks": [{"file": "a.py", "rank": 1, "header": "@@", "code": "+x"}]
            },
        },
        options=[TriageOption(label="Add P1", action="add_todo")],
    )


@pytest.mark.asyncio
async def test_sent_card_update_message_called_with_cardmessage():
    seen = {}

    async def _update(mid, card):
        seen["mid"], seen["card"] = mid, card
        return True

    messenger = MagicMock()
    messenger.update_message = AsyncMock(side_effect=_update)
    messenger.send_card = AsyncMock(return_value="new")
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "needs_review"})
    assert isinstance(seen["card"], CardMessage)
    assert seen["mid"] == "spaces/A/messages/p1"
    assert seen["card"].header.startswith("[Updated]")


@pytest.mark.asyncio
async def test_sent_card_update_false_falls_back_to_send_and_repersists_id():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=False)
    messenger.send_card = AsyncMock(return_value="spaces/A/messages/p2")
    sched, stores = _sched(messenger)
    card = _sent_card()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=card)
    stores.triage.get_card = AsyncMock(return_value=card)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "needs_review"})
    messenger.send_card.assert_awaited()
    assert any(
        c.args[0].bot_message_id == "spaces/A/messages/p2"
        for c in stores.triage.update_card.call_args_list
    )


@pytest.mark.asyncio
async def test_code_updated_runs_full_enrichment():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    enrich = AsyncMock(return_value={"context": {"curated_hunks": []}})
    with patch("workbench.pipeline.scheduler.enrich_item", new=enrich):
        await sched._fire_retriage(
            "it1",
            _result(change_type="code_updated"),
            _raw(diff_version="v2"),
            {"status": "x"},
        )
    enrich.assert_awaited()
    assert enrich.await_args.args[2] == "deep"


@pytest.mark.asyncio
async def test_light_path_reuses_stored_hunks_no_enrich():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    stores.triage.get_card = AsyncMock(return_value=_sent_card())
    enrich = AsyncMock(return_value={"context": {"curated_hunks": []}})
    with patch("workbench.pipeline.scheduler.enrich_item", new=enrich):
        await sched._fire_retriage(
            "it1", _result(change_type="status_changed"), _raw(), {"status": "x"}
        )
    enrich.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_cap_blocks_noncritical_before_llm():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    stores.triage.count_sent_today = AsyncMock(return_value=20)
    sched.llm.generate_triage_card = AsyncMock()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=_sent_card())
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ) as enrich:
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    enrich.assert_not_awaited()
    sched.llm.generate_triage_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_critical_bypasses_cap():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    stores.triage.count_sent_today = AsyncMock(return_value=99)
    stored = _sent_card()
    stores.triage.get_card_by_item_id = AsyncMock(return_value=stored)
    stores.triage.get_card = AsyncMock(return_value=stored)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage(
            "it1", _result(critical=True), _raw(), {"status": "x"}
        )
    messenger.update_message.assert_awaited()


@pytest.mark.asyncio
async def test_archived_item_is_noop():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    archived = _item()
    archived.status = ItemStatus.ARCHIVED
    stores.items.get_item = AsyncMock(return_value=archived)
    await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.update_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_card_updated_in_place_no_messenger_update():
    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    queued = _sent_card()
    queued.status = "queued"
    stores.triage.get_card_by_item_id = AsyncMock(return_value=queued)
    stores.triage.get_card = AsyncMock(return_value=queued)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.update_card.assert_awaited()
    messenger.update_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_responded_card_creates_new_card():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    responded = _sent_card()
    responded.status = "responded"
    stores.triage.get_card_by_item_id = AsyncMock(return_value=responded)
    stores.triage.get_card = AsyncMock(return_value=responded)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.save_card.assert_awaited()


@pytest.mark.asyncio
async def test_no_existing_card_creates_new_card():
    messenger = MagicMock()
    sched, stores = _sched(messenger)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=None)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.save_card.assert_awaited()


@pytest.mark.asyncio
async def test_deferred_card_cleared_before_update():
    from datetime import datetime, timezone

    messenger = MagicMock()
    messenger.update_message = AsyncMock(return_value=True)
    sched, stores = _sched(messenger)
    deferred = _sent_card()
    deferred.deferred_until = datetime.now(timezone.utc)
    stores.triage.get_card_by_item_id = AsyncMock(return_value=deferred)
    stores.triage.get_card = AsyncMock(return_value=deferred)
    with patch(
        "workbench.pipeline.scheduler.enrich_item",
        new=AsyncMock(return_value={"context": {}}),
    ):
        await sched._fire_retriage("it1", _result(), _raw(), {"status": "x"})
    stores.triage.clear_deferral.assert_awaited_once()
