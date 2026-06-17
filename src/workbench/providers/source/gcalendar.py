from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from workbench.domain import RawItem
from workbench.providers.source.base import SourceAdapter

logger = logging.getLogger(__name__)


def _compute_event_hash(event: dict) -> str:
    """Compute a deterministic hash of meaningful event fields for change detection."""
    title = event.get("summary", "")
    desc = event.get("description", "")
    start = event.get("start", {}).get(
        "dateTime", event.get("start", {}).get("date", "")
    )
    end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
    location = event.get("location", "")
    status = event.get("status", "")
    attendees_str = ",".join(
        sorted(a.get("email", "") for a in event.get("attendees", []))
    )
    content = f"{title}|{desc}|{start}|{end}|{location}|{status}|{attendees_str}"
    return hashlib.sha256(content.encode()).hexdigest()


class GCalendarAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        calendar_ids: list[str] = ["primary"]
        lookahead_hours: int = 48

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection
        self._event_hashes: dict[str, str] = {}

    def adapter_type(self) -> str:
        return "calendar"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        now = datetime.now(timezone.utc)
        time_min = since.isoformat() if since else now.isoformat()
        time_max = (now + timedelta(hours=self._config.lookahead_hours)).isoformat()

        items: list[RawItem] = []

        for cal_id in self._config.calendar_ids:

            def _fetch_events(cid=cal_id):
                result = (
                    self._connection.calendar.events()
                    .list(
                        calendarId=cid,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
                return result.get("items", [])

            events = await asyncio.to_thread(_fetch_events)

            for event in events:
                event_id = event.get("id", "")
                if not event_id:
                    continue

                # Hash-based dedup: skip unchanged events
                event_hash = _compute_event_hash(event)
                prev_hash = self._event_hashes.get(event_id)
                if prev_hash == event_hash:
                    continue
                self._event_hashes[event_id] = event_hash

                summary = event.get("summary", "(No title)")
                organizer = event.get("organizer", {}).get("email", "")
                attendees = [
                    {
                        "email": a.get("email", ""),
                        "response_status": a.get("responseStatus", ""),
                    }
                    for a in event.get("attendees", [])
                ]
                start_raw = event.get("start", {})
                end_raw = event.get("end", {})
                start_str = start_raw.get("dateTime", start_raw.get("date", ""))
                end_str = end_raw.get("dateTime", end_raw.get("date", ""))

                is_recurring = "recurringEventId" in event
                recurring_event_id = event.get("recurringEventId")

                # Compute starts_within_hours
                starts_within_hours = self._config.lookahead_hours
                try:
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    diff = (start_dt - now).total_seconds() / 3600.0
                    starts_within_hours = max(0, round(diff, 1))
                except (ValueError, TypeError):
                    logger.debug("Could not parse event start time %r", start_str)

                raw_text = json.dumps(
                    {
                        "summary": summary,
                        "organizer": organizer,
                        "attendees": attendees,
                        "location": event.get("location", ""),
                        "description": event.get("description", ""),
                        "start": start_str,
                        "end": end_str,
                        "is_recurring": is_recurring,
                        "recurring_event_id": recurring_event_id,
                        "link": event.get("htmlLink", ""),
                        "status": event.get("status", ""),
                    }
                )

                urgency_signals = {
                    "is_recurring": is_recurring,
                    "recurring_event_id": recurring_event_id,
                    "starts_within_hours": starts_within_hours,
                    "attendee_count": len(attendees),
                    "has_location": bool(event.get("location")),
                    "organizer": organizer,
                }

                items.append(
                    RawItem(
                        id=f"cal_{event_id}",
                        source_type="calendar",
                        source_label=f"Calendar: {summary[:80]}",
                        raw_text=raw_text,
                        urgency_signals=urgency_signals,
                        source_url=event.get("htmlLink") or None,
                    )
                )

        return items
