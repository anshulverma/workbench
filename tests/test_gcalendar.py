# tests/test_gcalendar.py

import hashlib
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
from workbench.providers.source.gcalendar import GCalendarAdapter
from workbench.providers.enrichment.gcalendar import GCalendarEnricher
from workbench.domain import ExtractedItem, RawItem, EnrichmentBudget, ItemCategory


# --- Helper to run sync functions as async (replaces asyncio.to_thread in tests) ---
async def _run_sync(fn, *a, **kw):
    return fn(*a, **kw)


def _make_event(
    event_id: str = "evt-1",
    summary: str = "Team Standup",
    start_hours_from_now: int = 2,
    duration_minutes: int = 30,
    organizer_email: str = "alice@meta.com",
    attendees: list[str] | None = None,
    location: str = "",
    description: str = "",
    recurring_event_id: str | None = None,
    status: str = "confirmed",
):
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=start_hours_from_now)
    end = start + timedelta(minutes=duration_minutes)
    event = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "organizer": {"email": organizer_email},
        "attendees": [{"email": e, "responseStatus": "accepted"} for e in (attendees or [])],
        "location": location,
        "description": description,
        "status": status,
        "htmlLink": f"https://calendar.google.com/event/{event_id}",
    }
    if recurring_event_id:
        event["recurringEventId"] = recurring_event_id
    return event


def _mock_connection_with_events(events: list[dict]):
    conn = MagicMock()
    events_list = MagicMock()
    events_list.execute.return_value = {"items": events}
    conn.calendar.events.return_value.list.return_value = events_list
    return conn


# ============ Adapter Tests ============

@pytest.mark.asyncio
async def test_poll_returns_raw_items():
    event = _make_event()
    conn = _mock_connection_with_events([event])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"], lookahead_hours=48)
    adapter = GCalendarAdapter(config, connection=conn)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    assert items[0].source_type == "calendar"
    assert items[0].id == f"cal_{event['id']}"
    raw = json.loads(items[0].raw_text)
    assert raw["summary"] == "Team Standup"
    assert raw["organizer"] == "alice@meta.com"


def test_adapter_type():
    adapter = GCalendarAdapter(GCalendarAdapter.ProviderConfig())
    assert adapter.adapter_type() == "calendar"


@pytest.mark.asyncio
async def test_poll_without_connection():
    adapter = GCalendarAdapter(GCalendarAdapter.ProviderConfig())
    items = await adapter.poll()
    assert items == []


@pytest.mark.asyncio
async def test_hash_based_dedup_skips_unchanged():
    event = _make_event(event_id="evt-stable")
    conn = _mock_connection_with_events([event])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"])
    adapter = GCalendarAdapter(config, connection=conn)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items1 = await adapter.poll()
        items2 = await adapter.poll()

    assert len(items1) == 1
    assert len(items2) == 0  # same hash, skipped


@pytest.mark.asyncio
async def test_hash_dedup_detects_change():
    event1 = _make_event(event_id="evt-change", summary="Standup")
    conn1 = _mock_connection_with_events([event1])

    config = GCalendarAdapter.ProviderConfig(calendar_ids=["primary"])
    adapter = GCalendarAdapter(config, connection=conn1)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items1 = await adapter.poll()

    # Event changes summary
    event2 = _make_event(event_id="evt-change", summary="Standup v2")
    conn2 = _mock_connection_with_events([event2])
    adapter._connection = conn2

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items2 = await adapter.poll()

    assert len(items1) == 1
    assert len(items2) == 1  # hash changed, re-emitted


@pytest.mark.asyncio
async def test_recurring_event_signals():
    event = _make_event(
        event_id="evt-rec-instance",
        recurring_event_id="evt-rec-master",
    )
    conn = _mock_connection_with_events([event])
    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["primary"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    signals = items[0].urgency_signals
    assert signals["is_recurring"] is True
    assert signals["recurring_event_id"] == "evt-rec-master"


@pytest.mark.asyncio
async def test_starts_within_hours_signal():
    event = _make_event(start_hours_from_now=1)
    conn = _mock_connection_with_events([event])
    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["primary"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 1
    signals = items[0].urgency_signals
    assert signals["starts_within_hours"] <= 2


@pytest.mark.asyncio
async def test_multiple_calendars():
    event_a = _make_event(event_id="evt-cal-a", summary="Cal A event")
    event_b = _make_event(event_id="evt-cal-b", summary="Cal B event")

    conn = MagicMock()
    call_count = {"n": 0}
    def _make_list_result(*a, **kw):
        mock = MagicMock()
        call_count["n"] += 1
        if call_count["n"] == 1:
            mock.execute.return_value = {"items": [event_a]}
        else:
            mock.execute.return_value = {"items": [event_b]}
        return mock
    conn.calendar.events.return_value.list = _make_list_result

    adapter = GCalendarAdapter(
        GCalendarAdapter.ProviderConfig(calendar_ids=["cal-a", "cal-b"]),
        connection=conn,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("workbench.providers.source.gcalendar.asyncio.to_thread", _run_sync)
        items = await adapter.poll()

    assert len(items) == 2


# ============ Enricher Tests ============

def _make_calendar_item(
    organizer: str = "alice@meta.com",
    attendees: list[str] | None = None,
    summary: str = "Team Standup",
) -> ExtractedItem:
    raw = RawItem(
        id="cal_evt-1",
        source_type="calendar",
        source_label="Calendar: Team Standup",
        raw_text=json.dumps({
            "summary": summary,
            "organizer": organizer,
            "attendees": [{"email": e, "response_status": "accepted"} for e in (attendees or [])],
            "location": "Room 5A",
            "description": "Weekly standup",
            "start": "2026-06-02T10:00:00+00:00",
            "end": "2026-06-02T10:30:00+00:00",
            "is_recurring": False,
            "link": "https://calendar.google.com/event/evt-1",
        }),
    )
    return ExtractedItem(
        summary=summary, category=ItemCategory.MEETING, source_context="", raw_item=raw,
    )


@pytest.mark.asyncio
async def test_enricher_returns_correct_shape():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    result = await enricher.enrich(_make_calendar_item(), "shallow", EnrichmentBudget())
    assert "calls_made" in result
    assert "time_ms" in result
    assert "context" in result
    assert isinstance(result["context"], dict)


@pytest.mark.asyncio
async def test_enricher_extracts_entity_refs():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    result = await enricher.enrich(
        _make_calendar_item(
            organizer="alice@meta.com",
            attendees=["bob@meta.com", "carol@meta.com"],
        ),
        "shallow", EnrichmentBudget(),
    )
    refs = result["context"]["entity_refs"]
    assert {"type": "person", "id": "gcal:alice@meta.com"} in refs
    assert {"type": "person", "id": "gcal:bob@meta.com"} in refs
    assert {"type": "person", "id": "gcal:carol@meta.com"} in refs


@pytest.mark.asyncio
async def test_enricher_non_calendar_returns_empty():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    raw = RawItem(id="gh-1", source_type="github", source_label="PR", raw_text="{}")
    item = ExtractedItem(
        summary="test", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw,
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget())
    assert result == {"calls_made": 0, "time_ms": 0, "context": {}}


@pytest.mark.asyncio
async def test_enricher_records_entities_in_memory():
    enricher = GCalendarEnricher(GCalendarEnricher.ProviderConfig())
    mock_memory = AsyncMock()
    await enricher.enrich(
        _make_calendar_item(organizer="alice@meta.com"),
        "shallow", EnrichmentBudget(), memory=mock_memory,
    )
    mock_memory.record_entity.assert_called()
    call_args = mock_memory.record_entity.call_args
    assert call_args[0][0] == "person"
    assert call_args[0][1] == "gcal:alice@meta.com"
