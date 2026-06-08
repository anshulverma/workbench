import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from workbench.models import TriageCard, TriageOption, TriageResponse


def _mock_stores():
    stores = MagicMock()
    stores.triage = AsyncMock()
    stores.items = AsyncMock()
    stores.filter_rules = AsyncMock()
    stores.interactions = AsyncMock()
    return stores


def test_defer_action_sets_deferred_until():
    """Responding with a defer option sets deferred_until and re-queues the card."""

    async def _test():
        mock_stores = _mock_stores()
        card = TriageCard(
            id="card-1",
            item_id="item-1",
            status="sent",
            options=[
                TriageOption(label="Snooze 4h", action="defer", details={"hours": 4}),
                TriageOption(label="Skip", action="skip"),
            ],
        )
        mock_stores.triage.get_card.return_value = card

        from workbench.api.triage import respond_to_triage

        request = MagicMock()
        request.app.state.stores = mock_stores
        request.app.state.memory = AsyncMock()

        response = TriageResponse(card_id="card-1", choice=1)

        result = await respond_to_triage(response, request)

        # Card should be updated
        assert mock_stores.triage.update_card.called
        updated_card = mock_stores.triage.update_card.call_args[0][0]
        assert updated_card.status == "queued"
        assert updated_card.deferred_until is not None
        # Deferred 4 hours from now (within a minute tolerance)
        expected_min = datetime.now(timezone.utc) + timedelta(hours=3, minutes=59)
        assert updated_card.deferred_until >= expected_min

    asyncio.run(_test())


def test_defer_action_in_scheduler():
    """Scheduler _handle_triage_response defers card and sends confirmation."""

    async def _test():
        mock_stores = _mock_stores()
        card = TriageCard(
            id="card-2",
            item_id="item-2",
            status="sent",
            card_content={"summary": "Test item", "source_type": "diff"},
            options=[
                TriageOption(label="Snooze 2h", action="defer", details={"hours": 2}),
                TriageOption(label="Skip", action="skip"),
            ],
        )

        from workbench.pipeline.scheduler import WorkbenchScheduler
        from workbench.memory.noop import NoopMemoryLayer
        from workbench.config import AppConfig

        config = AppConfig(
            storage={"postgres_dsn": "postgres://localhost/workbench"},
            llm={
                "class": "workbench.providers.llm.anthropic.AnthropicLLM",
                "api_key": "test",
            },
        )
        memory = NoopMemoryLayer()
        messenger = AsyncMock()
        pipeline = AsyncMock()

        scheduler = WorkbenchScheduler(
            stores=mock_stores,
            memory=memory,
            pipeline=pipeline,
            messenger=messenger,
            config=config,
        )

        await scheduler._handle_triage_response(card, choice=1)

        # Card should be deferred via update_card
        assert mock_stores.triage.update_card.called
        updated_card = mock_stores.triage.update_card.call_args[0][0]
        assert updated_card.status == "queued"
        assert updated_card.deferred_until is not None
        expected_min = datetime.now(timezone.utc) + timedelta(hours=1, minutes=59)
        assert updated_card.deferred_until >= expected_min

        # Confirmation message sent
        assert messenger.send_card.called

    asyncio.run(_test())


def test_other_action_sets_awaiting_followup():
    """Responding with an 'other' option sets status to awaiting_followup."""

    async def _test():
        mock_stores = _mock_stores()
        card = TriageCard(
            id="card-3",
            item_id="item-3",
            status="sent",
            options=[
                TriageOption(label="Other", action="other"),
                TriageOption(label="Skip", action="skip"),
            ],
        )
        mock_stores.triage.get_card.return_value = card

        from workbench.api.triage import respond_to_triage

        request = MagicMock()
        request.app.state.stores = mock_stores
        request.app.state.memory = AsyncMock()

        response = TriageResponse(card_id="card-3", choice=1)

        result = await respond_to_triage(response, request)

        assert mock_stores.triage.update_card.called
        updated_card = mock_stores.triage.update_card.call_args[0][0]
        assert updated_card.status == "awaiting_followup"

    asyncio.run(_test())


def test_defer_default_hours():
    """Defer action defaults to 4 hours when hours not specified in details."""

    async def _test():
        mock_stores = _mock_stores()
        card = TriageCard(
            id="card-4",
            item_id="item-4",
            status="sent",
            options=[
                TriageOption(label="Snooze", action="defer", details={}),
            ],
        )
        mock_stores.triage.get_card.return_value = card

        from workbench.api.triage import respond_to_triage

        request = MagicMock()
        request.app.state.stores = mock_stores
        request.app.state.memory = AsyncMock()

        response = TriageResponse(card_id="card-4", choice=1)

        result = await respond_to_triage(response, request)

        assert mock_stores.triage.update_card.called
        updated_card = mock_stores.triage.update_card.call_args[0][0]
        assert updated_card.status == "queued"
        # Default 4 hours
        expected_min = datetime.now(timezone.utc) + timedelta(hours=3, minutes=59)
        assert updated_card.deferred_until >= expected_min

    asyncio.run(_test())
