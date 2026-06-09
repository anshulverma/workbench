import pytest
from unittest.mock import AsyncMock
from workbench.domain import (
    Item, ItemCategory, ItemOrigin, ItemStatus, Priority,
)
from workbench.pipeline.scheduler import WorkbenchScheduler


class FakeItemStore:
    def __init__(self, items):
        self._items = items

    async def get_items(self, filters):
        result = self._items
        if filters.status:
            result = [i for i in result if i.status == filters.status]
        return result

    async def get_item(self, item_id):
        for i in self._items:
            if i.id == item_id:
                return i
        return None


class FakeTriageStore:
    async def get_pending(self):
        return []


class FakeIngestionQueueStore:
    async def queue_depth(self):
        return 0

    async def get_dead_letters(self):
        return []


class FakeStores:
    def __init__(self, items):
        self.items = FakeItemStore(items)
        self.triage = FakeTriageStore()
        self.ingestion_queue = FakeIngestionQueueStore()


@pytest.mark.asyncio
async def test_briefing_includes_action_items():
    items = [
        Item(
            source_type="email", source_id="e1",
            summary="Assign to bob", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P2,
            status=ItemStatus.ACTIVE,
            action_source="triage_response", action_category="delegation",
        ),
        Item(
            source_type="diff", source_id="d1",
            summary="Review RFC", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P1,
            status=ItemStatus.ACTIVE,
            action_source="triage_response", action_category="review",
        ),
    ]

    messenger = AsyncMock()
    from workbench.config import AppConfig, StorageConfig
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )

    scheduler = WorkbenchScheduler.__new__(WorkbenchScheduler)
    scheduler.stores = FakeStores(items)
    scheduler.memory = AsyncMock()
    scheduler.pipeline = AsyncMock()
    scheduler.messenger = messenger
    scheduler.config = config
    scheduler.sources = []

    await scheduler._morning_briefing_inner()

    call_args = messenger.send_card.call_args[0][0]
    assert "Pending actions" in call_args
    assert "Delegation" in call_args
    assert "Review" in call_args
    assert "Assign to bob" in call_args
    assert "Review RFC" in call_args


@pytest.mark.asyncio
async def test_briefing_no_actions_section_when_none():
    items = [
        Item(
            source_type="email", source_id="e1",
            summary="Regular task", category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED, priority=Priority.P1,
            status=ItemStatus.ACTIVE,
        ),
    ]

    messenger = AsyncMock()
    from workbench.config import AppConfig, StorageConfig
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x:x@localhost/x"),
        llm={"class": "x"},
    )

    scheduler = WorkbenchScheduler.__new__(WorkbenchScheduler)
    scheduler.stores = FakeStores(items)
    scheduler.memory = AsyncMock()
    scheduler.pipeline = AsyncMock()
    scheduler.messenger = messenger
    scheduler.config = config
    scheduler.sources = []

    await scheduler._morning_briefing_inner()

    call_args = messenger.send_card.call_args[0][0]
    assert "Pending actions" not in call_args
