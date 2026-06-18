import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from workbench.config import AppConfig, ServerConfig, StorageConfig
from workbench.providers.memory.noop import NoopMemoryLayer
from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    Priority,
    RawItem,
    TriageCard,
    JobTrigger,
)
from workbench.providers.source.base import SourceAdapter
from workbench.providers.change_detector.base import ChangeDetector, ChangeResult
from workbench.pipeline.scheduler import WorkbenchScheduler


class _Adapter(SourceAdapter):
    def __init__(self, monitoring=True, complete=True):
        self._m = monitoring
        self._c = complete

    async def poll(self, since=None):
        return []

    def adapter_type(self) -> str:
        return "diff"

    def supports_monitoring(self) -> bool:
        return self._m

    def poll_returns_complete_set(self) -> bool:
        return self._c

    def stable_id(self, raw_item: RawItem) -> str:
        return raw_item.id.split("_")[0]


class _Detector(ChangeDetector):
    def __init__(self, result: ChangeResult):
        self._r = result

    def detect(self, old_raw: dict, new_raw: dict) -> ChangeResult:
        return self._r

    def source_type(self) -> str:
        return "diff"


def _raw(rid, **payload):
    return RawItem(
        id=rid,
        source_type="diff",
        source_label=rid,
        raw_text=json.dumps(payload or {"status": "needs_review"}),
    )


def _result(material=False, terminal=False, ctype="status_changed"):
    return ChangeResult(
        is_material=material,
        is_terminal=terminal,
        changed_fields=["status"],
        change_type=ctype,
        reason="r",
    )


async def _save_item(stores, source_id, status=ItemStatus.ACTIVE, **raw):
    # A tracked source item is a root (parent_item_id IS NULL) under the lineage
    # model, so it must be born via create_root to get a materialized path. The
    # scheduler change-detection loop resolves it through the root-only
    # get_item_by_source_id.
    item = Item(
        source_type="diff",
        source_id=source_id,
        summary="s",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        status=status,
        raw_data={"raw_text": json.dumps(raw or {"status": "needs_review"})},
    )
    return await stores.items.create_root(item)


@pytest.fixture
def sched(stores):
    config = AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x/y"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "k"},
        server=ServerConfig(api_token="t"),
    )
    s = WorkbenchScheduler(
        stores,
        NoopMemoryLayer(),
        AsyncMock(),
        None,
        config,
        sources=[],
        llm=AsyncMock(),
    )
    s._debounce = MagicMock()
    return s


@pytest.mark.asyncio
async def test_new_item_enqueued_with_stable_id(sched):
    n = await sched._route_poll_results(
        "src", _Adapter(), _Detector(_result()), [_raw("D1_999")], JobTrigger.POLL
    )
    assert n == 1
    sched.pipeline.enqueue.assert_awaited_once()
    _, kwargs = sched.pipeline.enqueue.call_args
    assert kwargs["source_id"] == "D1"


@pytest.mark.asyncio
async def test_existing_material_change_updates_and_debounces(sched, stores):
    await _save_item(stores, "D1", status="needs_review" and ItemStatus.ACTIVE)
    await sched._route_poll_results(
        "src",
        _Adapter(),
        _Detector(_result(material=True)),
        [_raw("D1_999", status="accepted")],
        JobTrigger.POLL,
    )
    sched._debounce.schedule.assert_called_once()
    item = await stores.items.get_item_by_source_id("diff", "D1")
    assert json.loads(item.raw_data["raw_text"])["status"] == "accepted"


@pytest.mark.asyncio
async def test_existing_non_material_updates_silently(sched, stores):
    await _save_item(stores, "D1")
    await sched._route_poll_results(
        "src",
        _Adapter(),
        _Detector(_result(material=False)),
        [_raw("D1_999", status="accepted")],
        JobTrigger.POLL,
    )
    sched._debounce.schedule.assert_not_called()
    item = await stores.items.get_item_by_source_id("diff", "D1")
    assert json.loads(item.raw_data["raw_text"])["status"] == "accepted"


@pytest.mark.asyncio
async def test_terminal_archives_item_and_expires_card(sched, stores):
    item = await _save_item(stores, "D1")
    card = TriageCard(item_id=item.id, card_content={"summary": "x"}, status="queued")
    await stores.triage.save_card(card)
    await sched._route_poll_results(
        "src",
        _Adapter(),
        _Detector(_result(terminal=True)),
        [_raw("D1_999")],
        JobTrigger.POLL,
    )
    assert (await stores.items.get_item(item.id)).status == ItemStatus.ARCHIVED
    assert (await stores.triage.get_card(card.id)).status == "expired"


@pytest.mark.asyncio
async def test_disappeared_item_archived_when_complete_set(sched, stores):
    item = await _save_item(stores, "D2")
    card = TriageCard(item_id=item.id, card_content={"summary": "x"}, status="sent")
    await stores.triage.save_card(card)
    # poll returns a different item; D2 is absent -> disappeared
    await sched._route_poll_results(
        "src",
        _Adapter(complete=True),
        _Detector(_result()),
        [_raw("D9_1")],
        JobTrigger.POLL,
    )
    assert (await stores.items.get_item(item.id)).status == ItemStatus.ARCHIVED
    assert (await stores.triage.get_card(card.id)).status == "expired"


@pytest.mark.asyncio
async def test_disappeared_item_responded_card_untouched(sched, stores):
    item = await _save_item(stores, "D2")
    card = TriageCard(
        item_id=item.id, card_content={"summary": "x"}, status="responded"
    )
    await stores.triage.save_card(card)
    await sched._route_poll_results(
        "src",
        _Adapter(complete=True),
        _Detector(_result()),
        [_raw("D9_1")],
        JobTrigger.POLL,
    )
    assert (await stores.items.get_item(item.id)).status == ItemStatus.ARCHIVED
    assert (await stores.triage.get_card(card.id)).status == "responded"


@pytest.mark.asyncio
async def test_stable_id_migration_treats_old_compound_as_new(sched, stores):
    # Existing item stored under the OLD compound id; new stable id won't match.
    await _save_item(stores, "D3_111")
    n = await sched._route_poll_results(
        "src", _Adapter(), _Detector(_result()), [_raw("D3_222")], JobTrigger.POLL
    )
    assert n == 1  # treated as new ingestion
    sched.pipeline.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_set_does_not_archive_absent_items(sched, stores):
    item = await _save_item(stores, "D4")
    await sched._route_poll_results(
        "src",
        _Adapter(complete=False),
        _Detector(_result()),
        [_raw("D9_1")],
        JobTrigger.POLL,
    )
    assert (await stores.items.get_item(item.id)).status == ItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_seen_root_and_children_not_archived_on_complete_poll(sched, stores):
    # Gap-1 regression: get_active_by_source returns roots AND children; a root
    # whose stable source_id is present in a complete poll's seen_ids must NOT be
    # archived, and neither must its children (they share the same stable
    # source_id, set via the worker reconstructing raw_item.id = entry.source_id).
    root = await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D7",
            summary="root",
            category=ItemCategory.INFORMATIONAL,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority="P2",
            status=ItemStatus.EXTRACTED,
            raw_data={
                "raw_text": '{"status":"needs_review"}',
                "source_type": "diff",
                "id": "D7",
            },
        )
    )
    child = await stores.items.allocate_child(
        root,
        Item(
            source_type="diff",
            source_id="D7",
            summary="extracted",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.TRIAGED,
            priority="P2",
            status=ItemStatus.ACTIVE,
        ),
    )
    # Complete poll that still contains D7 (raw id "D7_222" -> stable_id "D7").
    await sched._route_poll_results(
        "src",
        _Adapter(complete=True),
        _Detector(_result()),
        [_raw("D7_222")],
        JobTrigger.POLL,
    )
    assert (await stores.items.get_item(root.id)).status == ItemStatus.EXTRACTED
    assert (await stores.items.get_item(child.id)).status == ItemStatus.ACTIVE
