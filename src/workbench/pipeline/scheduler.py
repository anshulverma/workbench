from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from workbench.alerting import AlertManager
from workbench.config import AppConfig, RetentionConfig
from workbench.memory.base import MemoryLayer
from workbench.models import (
    FilterRule,
    InteractionEntry,
    InterpretedResponse,
    Item,
    ItemCategory,
    ItemOrigin,
    ItemStatus,
    ItemUpdate,
    JobTrigger,
    Priority,
    SystemAction,
    TriageResponse,
    UserTodo,
)
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.llm.base import LLMProvider
from workbench.providers.messenger.base import Messenger
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class WorkbenchScheduler:
    def __init__(
        self,
        stores: Stores,
        memory: MemoryLayer,
        pipeline: PipelineEngine,
        messenger: Messenger | None,
        config: AppConfig,
        sources: list | None = None,
        llm: LLMProvider | None = None,
    ):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.config = config
        self.sources = sources or []
        self.llm = llm
        self.alert_manager = AlertManager(messenger, config.alerting)
        self.scheduler = AsyncIOScheduler(
            timezone=ZoneInfo(config.logging.timezone),
        )
        # Per-source asyncio.Lock so manual + scheduled polls of the same source serialize.
        self._source_locks: dict[str, asyncio.Lock] = {}
        # Maps source_id -> live adapter instance (kept in sync by hot-reload).
        self._source_by_id: dict[str, object] = {}
        # Stable DB source configs the scheduler manages (set at startup).
        self._db_sources: list = []

    def start(self):
        jobs = [
            (
                "triage_queue",
                "interval",
                {"seconds": self.config.triage.triage_poll_interval_seconds},
                self._manage_triage_queue,
            ),
            (
                "briefing",
                "cron",
                {"hour": self.config.scheduler.morning_briefing_hour},
                self._morning_briefing,
            ),
            ("expire_cards", "cron", {"hour": 3}, self._expire_cards),
        ]
        if self.config.alerting.enabled:
            jobs.append(
                (
                    "alert_check",
                    "interval",
                    {"minutes": self.config.scheduler.poll_interval_minutes},
                    self._alert_check,
                )
            )
        # Start the scheduler first, then register jobs. Adding jobs to a
        # running scheduler (rather than via the pending-jobs path) is reliable
        # when start() is called from within an already-running event loop.
        self.scheduler.start()

        for job_id, trigger, kwargs, func in jobs:
            logger.info(f"Scheduling job '{job_id}' ({trigger})")
            self.scheduler.add_job(func, trigger, id=job_id, **kwargs)

        # Per-source Source Jobs (replaces the global poll_sources interval job).
        # First runs are staggered a few seconds into the future to avoid a
        # simultaneous poll burst at startup.
        stagger = 5
        for source in self._db_sources:
            adapter = self._source_by_id.get(source.id)
            if adapter is None or not source.enabled:
                continue
            self.scheduler.add_job(
                self._poll_one_source,
                self._cron_trigger(source.schedule),
                id=f"poll_source:{source.id}",
                args=[source.id, JobTrigger.POLL],
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                next_run_time=datetime.now(ZoneInfo(self.config.logging.timezone))
                + timedelta(seconds=stagger),
            )
            stagger += 7
            logger.info(
                "Scheduled Source Job 'poll_source:%s' (%s)", source.id, source.schedule
            )

    def set_messenger(self, messenger: Messenger | None) -> None:
        """Rebind the messenger after a hot-swap (ADR 0013).

        Both the scheduler's own reference and the AlertManager's reference hold
        the messenger; a swap must update BOTH so triage sends and alerts use the
        new provider.
        """
        self.messenger = messenger
        # AlertManager stores the messenger as a private attribute (_messenger).
        self.alert_manager._messenger = messenger

    def _cron_trigger(self, schedule: str) -> CronTrigger:
        """Validate + build a CronTrigger; raises ValueError on a bad cron string."""
        return CronTrigger.from_crontab(
            schedule, timezone=ZoneInfo(self.config.logging.timezone)
        )

    def add_source_job(self, source, adapter) -> None:
        """Register one Source Job (CronTrigger) for an enabled source.

        Always records the id->adapter mapping; disabled sources get no job.
        Cron is validated via from_crontab before the adapter is mapped so a
        bad schedule surfaces clearly.
        """
        trigger = self._cron_trigger(source.schedule) if source.enabled else None
        self._source_by_id[source.id] = adapter
        if not source.enabled:
            return
        self.scheduler.add_job(
            self._poll_one_source,
            trigger,
            id=f"poll_source:{source.id}",
            args=[source.id, JobTrigger.POLL],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    def reschedule_source_job(self, source, adapter) -> None:
        self.remove_source_job(source.id)
        self.add_source_job(source, adapter)

    def remove_source_job(self, source_id: str) -> None:
        job = self.scheduler.get_job(f"poll_source:{source_id}")
        if job is not None:
            self.scheduler.remove_job(f"poll_source:{source_id}")
        self._source_by_id.pop(source_id, None)
        self._source_locks.pop(source_id, None)

    def _lock_for(self, source_id: str) -> asyncio.Lock:
        lock = self._source_locks.get(source_id)
        if lock is None:
            lock = asyncio.Lock()
            self._source_locks[source_id] = lock
        return lock

    async def _read_watermark(
        self, source_id: str, adapter_type: str
    ) -> datetime | None:
        stored = await self.stores.config.get(f"source_last_polled:{source_id}")
        if stored is None:
            # One-time non-destructive migration from the legacy adapter_type key.
            legacy = await self.stores.config.get(f"source_last_polled:{adapter_type}")
            if legacy is not None:
                await self.stores.config.set(f"source_last_polled:{source_id}", legacy)
                stored = legacy
        return datetime.fromisoformat(stored) if stored else None

    async def _poll_one_source(
        self, source_id: str, trigger: JobTrigger = JobTrigger.POLL
    ) -> None:
        """Shared by Source Jobs (POLL) and manual poll (MANUAL).

        Guarded by a per-source asyncio.Lock; owns Ingestion Run start/finish/error.
        """
        adapter = self._source_by_id.get(source_id)
        if adapter is None:
            logger.warning("No live adapter for source_id=%s", source_id)
            return
        adapter_type = adapter.adapter_type()

        async with self._lock_for(source_id):
            connection = getattr(adapter, "_connection", None)
            if connection is not None and hasattr(connection, "is_healthy"):
                if not connection.is_healthy():
                    logger.warning("Skipping %s: connection unhealthy", source_id)
                    return

            run_id = await self.stores.ingestion_runs.start_run(source_id)
            try:
                since = await self._read_watermark(source_id, adapter_type)
                raw_items = await adapter.poll(since=since)
                enqueued = 0
                for raw_item in raw_items:
                    try:
                        await self.pipeline.enqueue(
                            raw_item.raw_text,
                            raw_item.source_type,
                            source_id=raw_item.id,
                            urgency_signals=raw_item.urgency_signals,
                            trigger=trigger,
                        )
                        enqueued += 1
                    except Exception as e:
                        logger.error(
                            "Failed to enqueue item %s from %s: %s",
                            raw_item.id,
                            source_id,
                            e,
                        )
                await self.stores.config.set(
                    f"source_last_polled:{source_id}",
                    datetime.now(timezone.utc).isoformat(),
                )
                await self.stores.ingestion_runs.finish_run(run_id, enqueued)
                logger.info(
                    "Polled source %s (%s): %d items (since=%s)",
                    source_id,
                    adapter_type,
                    enqueued,
                    since,
                )
            except Exception as e:
                await self.stores.ingestion_runs.error_run(run_id, str(e))
                logger.error("Source %s poll failed: %s", source_id, e)

    async def _alert_check(self):
        """Build health dict and run alert checks."""
        try:
            health: dict = {}

            # Dead letter count
            dead_letters = await self.stores.ingestion_queue.get_dead_letters()
            health["dead_letter_count"] = len(dead_letters) if dead_letters else 0

            # Ingestion queue depth
            health["ingestion_queue_depth"] = (
                await self.stores.ingestion_queue.queue_depth()
            )

            # Connection health
            connections = {}
            for name, conn in getattr(self, "_connections", {}).items():
                try:
                    connections[name] = (
                        conn.is_healthy() if hasattr(conn, "is_healthy") else True
                    )
                except Exception:
                    logger.warning("Connection health check failed for %s", name)
                    connections[name] = False
            health["connections"] = connections

            await self.alert_manager.check_and_alert(health)
        except Exception:
            logger.error("Alert check failed", exc_info=True)

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

        # Timeout check for awaiting_followup/awaiting_confirmation cards
        for c in pending:
            if c.status in ("awaiting_followup", "awaiting_confirmation"):
                if (
                    c.sent_at
                    and (datetime.now(timezone.utc) - c.sent_at).total_seconds() > 3600
                ):
                    c.status = "expired"
                    c.response = "timed_out"
                    await self.stores.triage.update_card(c)
                    continue

        sent_cards = [c for c in pending if c.status == "sent"]
        awaiting_followup = [c for c in pending if c.status == "awaiting_followup"]
        awaiting_confirmation = [
            c for c in pending if c.status == "awaiting_confirmation"
        ]

        # Handle awaiting_confirmation cards first
        for card in awaiting_confirmation:
            responses = await self.messenger.poll_responses(card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip().lower()
                await self._handle_confirmation(card, text)
                return

        # Handle awaiting_followup cards
        for card in awaiting_followup:
            responses = await self.messenger.poll_responses(card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip()
                if text and self.llm:
                    interpreted = await self.llm.interpret_triage_response(card, text)
                    await self._execute_interpreted_response(interpreted, card)
                    return

        if sent_cards:
            card = sent_cards[0]
            responses = await self.messenger.poll_responses(card.bot_message_id)
            if responses:
                logger.debug(
                    "Got %d responses for card %s (msg=%s)",
                    len(responses),
                    card.id,
                    card.bot_message_id,
                )
            for resp in responses:
                text = resp.get("text", "").strip()
                lower_text = text.lower()
                if lower_text in ("skip all", "skip remaining"):
                    for c in pending:
                        if c.responded_at is None:
                            await self.stores.triage.record_response(
                                c.id,
                                TriageResponse(
                                    card_id=c.id, choice=0, raw_text="skip all"
                                ),
                            )
                    return
                try:
                    choice = int(text)
                    if 1 <= choice <= len(card.options):
                        option = card.options[choice - 1]
                        if option.action == "other":
                            # Transition to awaiting_followup
                            card.status = "awaiting_followup"
                            await self.stores.triage.update_card(card)
                            await self.messenger.send_card("What would you like to do?")
                            return
                        await self._handle_triage_response(card, choice)
                        return
                except ValueError:
                    # Free-text response -- interpret via LLM
                    if self.llm:
                        interpreted = await self.llm.interpret_triage_response(
                            card, text
                        )
                        await self._execute_interpreted_response(interpreted, card)
                        return
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
                    card.item_id,
                    ItemUpdate(priority=priority, status=ItemStatus.ACTIVE),
                )
            else:
                item = Item(
                    source_type=card.card_content.get("source_type", "unknown"),
                    source_id=card.id,
                    summary=card.card_content.get("summary", ""),
                    category=ItemCategory.ACTION_ITEM,
                    origin=ItemOrigin.TRIAGED,
                    priority=priority,
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

        # FIX 6: Actual InteractionEntry, not a placeholder comment
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_id=card.item_id,
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen=option.label,
            choice_index=choice,
        )
        await self.stores.interactions.append(entry)
        await self.memory.record_triage(card, response)

        if self.messenger:
            await self.messenger.send_card(f"Got it -- {option.label}")

    async def _execute_interpreted_response(
        self, interpreted: InterpretedResponse, card
    ) -> None:
        """Execute an LLM-interpreted free-text response.

        FIX 34: Destructive actions (skip, mute_pattern) require confirmation
        and return early. Defer also returns early.
        FIX 20: Store pending InterpretedResponse before entering awaiting_confirmation.
        FIX 6: Append actual InteractionEntry with interpreted data.
        FIX 32: Priority string -> enum conversion.
        """
        for action in interpreted.system_actions:
            # Destructive actions require confirmation
            if action.action in ("skip", "mute_pattern"):
                # FIX 20: Store pending InterpretedResponse in card_content
                card.card_content["pending_interpreted"] = interpreted.model_dump()
                card.status = "awaiting_confirmation"
                await self.stores.triage.update_card(card)
                if self.messenger:
                    await self.messenger.send_card(
                        f"I understood: {interpreted.explanation}\n"
                        f"Reply 'yes' to confirm or 'no' to cancel."
                    )
                # Close the audit gap: the Interaction Log must record every
                # response, including the destructive-pending branch that
                # returns early awaiting confirmation.
                entry = InteractionEntry(
                    source_type=card.card_content.get("source_type", "unknown"),
                    item_id=card.item_id,
                    item_summary=card.card_content.get("summary", ""),
                    triage_card_full=card.card_content,
                    options_presented=[o.model_dump() for o in card.options],
                    option_chosen="free_text_pending_confirmation",
                    type="free_text",
                    interpreted=interpreted.model_dump(),
                )
                await self.stores.interactions.append(entry)
                # FIX 34: Return early -- do not process further actions
                return

            elif action.action == "add_todo":
                # FIX 32: Priority string -> enum
                priority = Priority(action.details.get("priority", "P2"))
                if card.item_id:
                    await self.stores.items.update_item(
                        card.item_id,
                        ItemUpdate(priority=priority, status=ItemStatus.ACTIVE),
                    )
                else:
                    item = Item(
                        source_type=card.card_content.get("source_type", "unknown"),
                        source_id=card.id,
                        summary=card.card_content.get("summary", ""),
                        category=ItemCategory.ACTION_ITEM,
                        origin=ItemOrigin.TRIAGED,
                        priority=priority,
                        status=ItemStatus.ACTIVE,
                    )
                    await self.stores.items.save_item(item)

            elif action.action == "defer":
                hours = action.details.get("hours", 4)
                card.deferred_until = datetime.now(timezone.utc) + timedelta(
                    hours=hours
                )
                card.status = "queued"
                await self.stores.triage.update_card(card)
                # Close the audit gap: log the deferral before returning early.
                entry = InteractionEntry(
                    source_type=card.card_content.get("source_type", "unknown"),
                    item_id=card.item_id,
                    item_summary=card.card_content.get("summary", ""),
                    triage_card_full=card.card_content,
                    options_presented=[o.model_dump() for o in card.options],
                    option_chosen="free_text_deferred",
                    type="free_text",
                    interpreted=interpreted.model_dump(),
                )
                await self.stores.interactions.append(entry)
                # FIX 34: Defer returns early
                return

        # Create user todos as action items
        for todo in interpreted.user_todos:
            new_item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=todo.summary,
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=Priority.P2,
                status=ItemStatus.ACTIVE,
                parent_item_id=card.item_id,
                action_source="triage_response",
                action_category=todo.action_category,
            )
            await self.stores.items.save_item(new_item)

        # Mark card as responded
        card.status = "responded"
        card.responded_at = datetime.now(timezone.utc)
        await self.stores.triage.update_card(card)

        # FIX 6: Append actual InteractionEntry with interpreted response data
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_id=card.item_id,
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen="free_text",
            type="free_text",
            interpreted=interpreted.model_dump(),
        )
        await self.stores.interactions.append(entry)

        if self.messenger:
            await self.messenger.send_card(f"Done! {interpreted.explanation}")

    async def _handle_confirmation(self, card, text: str) -> None:
        """FIX 7: Handle 'yes'/'no' response to awaiting_confirmation cards.

        FIX 20: Retrieve stored InterpretedResponse from card.card_content["pending_interpreted"].
        """
        if text.lower() in ("yes", "y", "confirm"):
            pending_data = card.card_content.get("pending_interpreted")
            if not pending_data:
                logger.warning("No pending_interpreted found for card %s", card.id)
                card.status = "responded"
                card.responded_at = datetime.now(timezone.utc)
                await self.stores.triage.update_card(card)
                return

            # Reconstruct InterpretedResponse
            interpreted = InterpretedResponse(**pending_data)

            # Execute the destructive actions directly (no re-confirmation)
            for action in interpreted.system_actions:
                if action.action == "skip":
                    if card.item_id:
                        await self.stores.items.update_item(
                            card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
                        )
                elif action.action == "mute_pattern":
                    rule = FilterRule(
                        source_type=card.card_content.get("source_type"),
                        pattern=card.card_content.get("summary", ""),
                        action="drop",
                        created_from_interaction_id=card.id,
                    )
                    await self.stores.filter_rules.add_rule(rule)

            # Mark card as responded
            card.status = "responded"
            card.responded_at = datetime.now(timezone.utc)
            # Clean up pending data
            card.card_content.pop("pending_interpreted", None)
            await self.stores.triage.update_card(card)

            # FIX 6: Log interaction
            entry = InteractionEntry(
                source_type=card.card_content.get("source_type", "unknown"),
                item_id=card.item_id,
                item_summary=card.card_content.get("summary", ""),
                triage_card_full=card.card_content,
                options_presented=[o.model_dump() for o in card.options],
                option_chosen="confirmed",
                type="free_text",
                interpreted=interpreted.model_dump(),
                confirmed=True,
            )
            await self.stores.interactions.append(entry)

            if self.messenger:
                await self.messenger.send_card("Confirmed. Done!")

        elif text.lower() in ("no", "n", "cancel"):
            card.status = "sent"  # Return to sent state for re-triage
            card.card_content.pop("pending_interpreted", None)
            await self.stores.triage.update_card(card)

            if self.messenger:
                await self.messenger.send_card(
                    "Cancelled. The card is back in your queue."
                )

        else:
            # Unrecognized -- re-prompt
            if self.messenger:
                await self.messenger.send_card(
                    "Please reply 'yes' to confirm or 'no' to cancel."
                )

    async def _expire_cards(self):
        expired = await self.stores.triage.expire_old_cards(
            self.config.triage.expiry_days
        )
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
            oldest = min(
                c.sent_at or c.expires_at or datetime.now(timezone.utc) for c in pending
            )
            age_days = (datetime.now(timezone.utc) - oldest).days
            lines.append(
                f"\n*Pending triage:* {len(pending)} cards (oldest: {age_days}d)"
            )

        if queue_depth > 0 or dead_letters:
            lines.append(f"\n*Queue health:* {queue_depth} queued")
            if dead_letters:
                lines.append(
                    f"  ⚠ {len(dead_letters)} dead-letter entries need investigation"
                )

        if not p0 and not p1 and not pending and not action_items:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))

        # Run daily retention cleanup after briefing
        try:
            retention_result = await run_retention_cleanup(
                self.stores, self.config.retention
            )
            total = sum(retention_result.values())
            if total > 0:
                logger.info(
                    "Retention cleanup ran after morning briefing",
                    extra=retention_result,
                )
        except Exception:
            logger.error("Retention cleanup failed", exc_info=True)


async def run_retention_cleanup(stores, config: RetentionConfig) -> dict[str, int]:
    """Run daily retention cleanup. Returns counts of deleted rows."""
    results: dict[str, int] = {}

    results["archived_items"] = await stores.items.delete_older_than(
        "archived", config.archived_items_days
    )
    results["done_items"] = await stores.items.delete_older_than(
        "done", config.done_items_days
    )
    results["expired_cards"] = await stores.triage.delete_older_than(
        "expired", config.expired_cards_days
    )
    results["responded_cards"] = await stores.triage.delete_older_than(
        "responded", config.responded_cards_days
    )
    results["enrichment_traces"] = await stores.enrichment.delete_older_than(
        config.enrichment_traces_days
    )
    results["dead_letters"] = (
        await stores.ingestion_queue.delete_dead_letters_older_than(
            config.dead_letters_days
        )
    )
    results["ingestion_runs"] = await stores.ingestion_runs.delete_older_than(
        config.ingestion_runs_days
    )

    total = sum(results.values())
    if total > 0:
        logger.info("retention_cleanup_complete", extra={**results, "total": total})
    return results
