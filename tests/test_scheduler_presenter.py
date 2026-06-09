import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.domain import TriageCard, TriageOption, CardMessage
from workbench.pipeline.presenter import PlainCardPresenter
from workbench.pipeline.scheduler import WorkbenchScheduler


def _card():
    return TriageCard(
        id="c1",
        card_content={
            "summary": "Review D123",
            "card_body": "Review D123",
            "source_type": "diff",
        },
        options=[TriageOption(label="Add P1", action="add_todo")],
        status="queued",
    )


def _scheduler(messenger, presenter):
    stores = MagicMock()
    stores.triage.count_sent_today = AsyncMock(return_value=0)
    # A queued card appears in get_pending (status IN queued/sent/awaiting) AND
    # is returned by get_next_unsent — mirror that so the send block is reached.
    stores.triage.get_pending = AsyncMock(return_value=[_card()])
    stores.triage.get_next_unsent = AsyncMock(return_value=_card())
    stores.triage.update_card = AsyncMock()
    config = MagicMock()
    config.triage.daily_cap = 20
    config.logging.timezone = "UTC"
    config.alerting.enabled = False
    sched = WorkbenchScheduler(stores, MagicMock(), MagicMock(), messenger, config)
    sched.presenter = presenter
    return sched, stores


@pytest.mark.asyncio
async def test_sends_cardmessage_via_presenter():
    sent = {}

    async def _send(card):
        sent["card"] = card
        return "msg-1"

    messenger = MagicMock()
    messenger.send_card = AsyncMock(side_effect=_send)
    messenger.poll_responses = AsyncMock(return_value=[])
    sched, stores = _scheduler(messenger, PlainCardPresenter())

    await sched._manage_triage_queue_inner()

    assert isinstance(sent["card"], CardMessage)
    assert "Review D123" in sent["card"].header or any(
        "Review D123" in s.body for s in sent["card"].sections
    )
    stores.triage.update_card.assert_awaited()
