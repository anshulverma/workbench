from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from workbench.config import AppConfig
from workbench.memory.base import MemoryLayer
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, JobTrigger, Priority, TriageResponse,
)
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.messenger.base import Messenger
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine,
                 messenger: Messenger | None, config: AppConfig, sources: list | None = None):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.config = config
        self.sources = sources or []
        self.scheduler = AsyncIOScheduler(
            timezone=ZoneInfo(config.logging.timezone),
        )

    def start(self):
        jobs = [
            ("triage_queue", "interval",
             {"seconds": self.config.triage.triage_poll_interval_seconds},
             self._manage_triage_queue),
            ("briefing", "cron",
             {"hour": self.config.scheduler.morning_briefing_hour},
             self._morning_briefing),
            ("expire_cards", "cron", {"hour": 3}, self._expire_cards),
        ]
        if self.sources:
            jobs.append((
                "poll_sources", "interval",
                {"minutes": self.config.scheduler.poll_interval_minutes},
                self._poll_sources,
            ))
        for job_id, trigger, kwargs, func in jobs:
            logger.info(f"Scheduling job '{job_id}' ({trigger})")
            self.scheduler.add_job(func, trigger, id=job_id, **kwargs)
        self.scheduler.start()

    async def _poll_sources(self):
        for source in self.sources:
            adapter_type = source.adapter_type()
            try:
                connection = getattr(source, '_connection', None)
                if connection is not None and hasattr(connection, 'is_healthy'):
                    if not connection.is_healthy():
                        logger.warning("Skipping %s: connection unhealthy", adapter_type)
                        continue

                since = None
                stored = await self.stores.config.get(f"source_last_polled:{adapter_type}")
                if stored:
                    since = datetime.fromisoformat(stored)

                raw_items = await source.poll(since=since)
                for raw_item in raw_items:
                    try:
                        await self.pipeline.enqueue(
                            raw_item.raw_text,
                            raw_item.source_type,
                            source_id=raw_item.id,
                            urgency_signals=raw_item.urgency_signals,
                            trigger=JobTrigger.POLL,
                        )
                    except Exception as e:
                        logger.error("Failed to enqueue item %s from %s: %s",
                                     raw_item.id, adapter_type, e)

                await self.stores.config.set(
                    f"source_last_polled:{adapter_type}",
                    datetime.now(timezone.utc).isoformat(),
                )
                logger.info("Polled %s: %d items (since=%s)", adapter_type, len(raw_items), since)
            except Exception as e:
                logger.error("Source adapter %s poll failed: %s", adapter_type, e)

    async def _manage_triage_queue(self):
        if not self.messenger:
            return

        try:
            await self._manage_triage_queue_inner()
        except Exception:
            logger.error("Triage queue management failed", exc_info=True)

    async def _manage_triage_queue_inner(self):
        sent_today = await self.stores.triage.count_sent_today()
        if sent_today >= self.config.triage.daily_cap:
            return

        pending = await self.stores.triage.get_pending()
        if not pending:
            return

        sent_cards = [c for c in pending if c.status == "sent"]
        if sent_cards:
            card = sent_cards[0]
            responses = await self.messenger.poll_responses(card.bot_message_id)
            if responses:
                logger.info("Got %d responses for card %s (msg=%s)", len(responses), card.id, card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip().lower()
                if text in ("skip all", "skip remaining"):
                    for c in pending:
                        if c.responded_at is None:
                            await self.stores.triage.record_response(
                                c.id, TriageResponse(card_id=c.id, choice=0, raw_text="skip all")
                            )
                    return
                try:
                    choice = int(text)
                    if 1 <= choice <= len(card.options):
                        await self._handle_triage_response(card, choice)
                        return
                except ValueError:
                    pass
            return

        card = await self.stores.triage.get_next_unsent()
        if not card:
            return

        text = format_card_for_chat(card, position=1, total=len(pending))
        msg_id = await self.messenger.send_card(text)
        card.status = "sent"
        card.sent_at = datetime.now(timezone.utc)
        card.bot_message_id = msg_id
        card.daily_sequence = sent_today + 1
        await self.stores.triage.update_card(card)

    async def _handle_triage_response(self, card, choice: int):
        option = card.options[choice - 1]
        response = TriageResponse(card_id=card.id, choice=choice)
        await self.stores.triage.record_response(card.id, response)

        if option.action == "add_todo":
            priority = Priority(option.details.get("priority", "P2"))
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
                )
            else:
                item = Item(
                    source_type=card.card_content.get("source_type", "unknown"),
                    source_id=card.id,
                    summary=card.card_content.get("summary", ""),
                    category=ItemCategory.ACTION_ITEM,
                    origin=ItemOrigin.TRIAGED, priority=priority,
                    status=ItemStatus.ACTIVE,
                )
                await self.stores.items.save_item(item)

        elif option.action == "skip":
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
                )

        elif option.action == "mute_pattern":
            rule = FilterRule(
                source_type=card.card_content.get("source_type"),
                pattern=card.card_content.get("summary", ""),
                action="drop",
                created_from_interaction_id=card.id,
            )
            await self.stores.filter_rules.add_rule(rule)

        elif option.action == "defer":
            hours = option.details.get("hours", 4)
            card.deferred_until = datetime.now(timezone.utc) + timedelta(hours=hours)
            card.status = "queued"
            await self.stores.triage.update_card(card)

        elif option.action == "other":
            card.status = "awaiting_followup"
            await self.stores.triage.update_card(card)

        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen=option.label,
        )
        await self.stores.interactions.append(entry)
        await self.memory.record_triage(card, response)

        if self.messenger:
            await self.messenger.send_card(f"Got it — {option.label}")

    async def _expire_cards(self):
        expired = await self.stores.triage.expire_old_cards(self.config.triage.expiry_days)
        if expired:
            logger.info(f"Auto-expired {expired} triage cards")

    async def _morning_briefing(self):
        if not self.messenger:
            return
        try:
            await self._morning_briefing_inner()
        except Exception:
            logger.error("Morning briefing failed", exc_info=True)

    async def _morning_briefing_inner(self):
        from workbench.models import ItemFilters
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()
        queue_depth = await self.stores.ingestion_queue.queue_depth()
        dead_letters = await self.stores.ingestion_queue.get_dead_letters()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]

        if p0:
            lines.append(f"*P0 — Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        if p1:
            lines.append(f"*P1 — This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        action_items = [i for i in items if i.action_source is not None]
        if action_items:
            from collections import defaultdict
            by_category = defaultdict(list)
            for item in action_items:
                cat = (item.action_category or "uncategorized").title()
                parent_summary = ""
                if item.parent_item_id:
                    parent = await self.stores.items.get_item(item.parent_item_id)
                    if parent:
                        parent_summary = f" — from {parent.summary}"
                by_category[cat].append(f"    • {item.summary}{parent_summary}")
            lines.append(f"\n*Pending actions ({len(action_items)}):*")
            for cat, cat_items in by_category.items():
                lines.append(f"  {cat} ({len(cat_items)}):")
                lines.extend(cat_items)

        if pending:
            oldest = min(c.sent_at or c.expires_at or datetime.now(timezone.utc) for c in pending)
            age_days = (datetime.now(timezone.utc) - oldest).days
            lines.append(f"\n*Pending triage:* {len(pending)} cards (oldest: {age_days}d)")

        if queue_depth > 0 or dead_letters:
            lines.append(f"\n*Queue health:* {queue_depth} queued")
            if dead_letters:
                lines.append(f"  ⚠ {len(dead_letters)} dead-letter entries need investigation")

        if not p0 and not p1 and not pending and not action_items:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
