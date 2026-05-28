# server/pipeline/scheduler.py
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from workbench.storage.base import Stores
from workbench.memory.base import MemoryLayer
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.messenger.base import Messenger
from workbench.models import TriageResponse, InteractionEntry, FilterRule, ItemOrigin, ItemCategory, Priority, Item

logger = logging.getLogger(__name__)

class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine, messenger: Messenger | None, settings):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.settings = settings
        self.scheduler = AsyncIOScheduler()
        self._last_bot_message_id: str | None = None

    def start(self):
        self.scheduler.add_job(self._poll_sources, "interval", minutes=self.settings.poll_interval_minutes, id="poll")
        self.scheduler.add_job(self._manage_triage_queue, "interval", seconds=30, id="triage_queue")
        self.scheduler.add_job(self._morning_briefing, "cron", hour=self.settings.morning_briefing_hour, id="briefing")
        self.scheduler.start()

    async def _poll_sources(self):
        sources = await self.stores.sources.get_sources()
        for source in sources:
            if not source.enabled:
                continue
            logger.info(f"Polling {source.adapter_type}")
            # Source polling will be implemented when source adapters are wired up

    async def _manage_triage_queue(self):
        if not self.messenger:
            return
        pending = await self.stores.triage.get_pending()
        if not pending:
            return

        # Send the first unsent card
        card = pending[0]
        if card.sent_at is None:
            text = format_card_for_chat(card, position=1, total=len(pending))
            msg_id = await self.messenger.send_card(text)
            card.sent_at = datetime.utcnow()
            await self.stores.triage.save_card(card)
            self._last_bot_message_id = msg_id
            return

        # Poll for response to the current card
        responses = await self.messenger.poll_responses(self._last_bot_message_id)
        for resp in responses:
            text = resp.get("text", "").strip().lower()
            if text == "skip all" or text == "skip remaining":
                # Mark all pending as skipped
                for c in pending:
                    if c.responded_at is None:
                        await self.stores.triage.record_response(c.id, TriageResponse(card_id=c.id, choice=0, raw_text="skip all"))
                return

            try:
                choice = int(text)
                if 1 <= choice <= len(card.options):
                    await self._handle_triage_response(card, choice)
                    return
            except ValueError:
                pass

    async def _handle_triage_response(self, card, choice: int):
        option = card.options[choice - 1]
        response = TriageResponse(card_id=card.id, choice=choice)
        await self.stores.triage.record_response(card.id, response)

        if option.action == "add_todo":
            priority = Priority(option.details.get("priority", "P2"))
            item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=card.card_content.get("summary", ""),
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=priority,
            )
            await self.stores.items.save_item(item)

        elif option.action == "mute_pattern":
            rule = FilterRule(
                source_type=card.card_content.get("source_type"),
                pattern=card.card_content.get("summary", ""),
                action="drop",
                created_from_interaction_id=card.id,
            )
            await self.stores.filter_rules.add_rule(rule)

        # Log interaction
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen=option.label,
        )
        await self.stores.interactions.append(entry)
        await self.memory.record_triage(card, response)

    async def _morning_briefing(self):
        if not self.messenger:
            return
        from workbench.models import ItemFilters, ItemStatus
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]
        if p0:
            lines.append(f"*P0 — Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  - {i.summary} [{i.source_type}]")
        if p1:
            lines.append(f"*P1 — This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  - {i.summary} [{i.source_type}]")
        if pending:
            lines.append(f"\n_{len(pending)} items pending triage_")
        if not p0 and not p1 and not pending:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
