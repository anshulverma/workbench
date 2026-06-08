from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from workbench.models import RawItem
from workbench.providers.source.base import SourceAdapter

logger = logging.getLogger(__name__)

_THREAD_EXIT_HOURS = 48


class GChatAdapter(SourceAdapter):
    """Google Chat source adapter with thread subscription model.

    Track modes:
      - "all": emit all threads with new messages
      - "participating": only threads where user_id has posted
      - "mentioned": only threads where user_id is @-mentioned
    """

    class ProviderConfig(BaseModel):
        spaces: list[str] = []
        exclude_spaces: list[str] = []
        track: str = "all"  # "participating" | "mentioned" | "all"
        user_id: str = (
            ""  # e.g. "users/user-me", required for participating/mentioned modes
        )

    def __init__(self, config: ProviderConfig, connection=None):
        self._config = config
        self._connection = connection
        self._tracked_threads: dict[str, datetime] = {}

    def adapter_type(self) -> str:
        return "chat"

    async def poll(self, since: datetime | None = None) -> list[RawItem]:
        if not self._connection:
            return []

        items: list[RawItem] = []
        now = datetime.now(timezone.utc)

        # Expire stale tracked threads (no activity for 48h)
        stale_threads = [
            tid
            for tid, last_active in self._tracked_threads.items()
            if (now - last_active).total_seconds() > _THREAD_EXIT_HOURS * 3600
        ]
        for tid in stale_threads:
            del self._tracked_threads[tid]
            logger.debug("Thread exited (48h inactivity): %s", tid)

        effective_spaces = [
            s for s in self._config.spaces if s not in self._config.exclude_spaces
        ]

        for space_name in effective_spaces:

            def _fetch_messages(sn=space_name):
                result = (
                    self._connection.chat.spaces()
                    .messages()
                    .list(
                        parent=sn,
                        pageSize=100,
                    )
                    .execute()
                )
                return result.get("messages", [])

            raw_messages = await asyncio.to_thread(_fetch_messages)

            # Filter bot messages
            human_messages = [
                m
                for m in raw_messages
                if m.get("sender", {}).get("type", "HUMAN") != "BOT"
            ]

            # Group by thread
            threads: dict[str, list[dict]] = {}
            for msg in human_messages:
                thread_name = msg.get("thread", {}).get("name", "")
                if not thread_name:
                    continue
                threads.setdefault(thread_name, []).append(msg)

            for thread_name, thread_msgs in threads.items():
                # Apply track mode filter
                if not self._should_track(thread_name, thread_msgs):
                    continue

                # Update thread tracking timestamp
                latest_time = self._get_latest_time(thread_msgs)
                if (now - latest_time).total_seconds() > _THREAD_EXIT_HOURS * 3600:
                    continue
                self._tracked_threads[thread_name] = latest_time

                # Build the raw text with full thread context
                space_display = (
                    thread_msgs[0].get("space", {}).get("displayName", space_name)
                )
                formatted_messages = []
                for m in thread_msgs:
                    formatted_messages.append(
                        {
                            "sender_name": m.get("sender", {}).get("name", ""),
                            "sender_display": m.get("sender", {}).get(
                                "displayName", ""
                            ),
                            "text": m.get("text", ""),
                            "create_time": m.get("createTime", ""),
                        }
                    )

                participant_names = list(
                    set(
                        m["sender_display"]
                        for m in formatted_messages
                        if m["sender_display"]
                    )
                )

                # source_id includes thread name and latest timestamp for dedup
                latest_ts = int(latest_time.timestamp())
                source_id = f"gchat_{thread_name.replace('/', '_')}_{latest_ts}"

                raw_text = json.dumps(
                    {
                        "space_name": space_display,
                        "thread_name": thread_name,
                        "messages": formatted_messages,
                        "participant_count": len(participant_names),
                        "participants": participant_names,
                    }
                )

                urgency_signals = {
                    "space": space_display,
                    "thread": thread_name,
                    "participant_count": len(participant_names),
                    "message_count": len(formatted_messages),
                    "is_direct_message": len(participant_names) <= 2,
                }

                items.append(
                    RawItem(
                        id=source_id,
                        source_type="chat",
                        source_label=f"Chat: {space_display}",
                        raw_text=raw_text,
                        urgency_signals=urgency_signals,
                    )
                )

        return items

    def _should_track(self, thread_name: str, messages: list[dict]) -> bool:
        """Determine if a thread should be tracked based on the track mode."""
        track = self._config.track
        user_id = self._config.user_id

        if track == "all":
            return True

        if track == "participating":
            # Track if user has posted in this thread
            for msg in messages:
                if msg.get("sender", {}).get("name") == user_id:
                    return True
            # Also track if already tracked (re-entry happens via user posting)
            return thread_name in self._tracked_threads

        if track == "mentioned":
            # Track if user is @-mentioned in any message
            for msg in messages:
                text = msg.get("text", "")
                if user_id and user_id in text:
                    return True
            return False

        return True

    def _get_latest_time(self, messages: list[dict]) -> datetime:
        """Get the latest createTime from a list of messages."""
        latest: datetime | None = None
        for msg in messages:
            create_time = msg.get("createTime", "")
            if create_time:
                try:
                    dt = datetime.fromisoformat(create_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if latest is None or dt > latest:
                        latest = dt
                except (ValueError, TypeError):
                    logger.debug("Could not parse message createTime %r", create_time)
        return latest or datetime.now(timezone.utc)
