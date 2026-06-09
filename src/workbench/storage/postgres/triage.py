from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import asyncpg

from workbench.domain import TriageCard, TriageOption, TriageResponse
from workbench.storage.base import TriageStore


class PgTriageStore(TriageStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_pending(self) -> list[TriageCard]:
        rows = await self.pool.fetch(
            "SELECT * FROM triage_cards WHERE status IN ('queued', 'sent', 'awaiting_followup', 'awaiting_confirmation') "
            "ORDER BY relevance_score DESC"
        )
        return [self._row_to_card(r) for r in rows]

    async def get_next_unsent(self) -> TriageCard | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM triage_cards WHERE status = 'queued' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) "
            "ORDER BY relevance_score DESC LIMIT 1"
        )
        return self._row_to_card(row) if row else None

    async def save_card(self, card: TriageCard) -> TriageCard:
        await self.pool.execute(
            """INSERT INTO triage_cards
               (id, item_id, card_content, options, relevance_score,
                confidence_score, status, bot_message_id, daily_sequence,
                expires_at, sent_at, responded_at, response, deferred_until,
                created_at)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8, $9,
                       $10, $11, $12, $13, $14, $15)
               ON CONFLICT (id) DO UPDATE SET
                 item_id = EXCLUDED.item_id,
                 card_content = EXCLUDED.card_content,
                 options = EXCLUDED.options,
                 relevance_score = EXCLUDED.relevance_score,
                 confidence_score = EXCLUDED.confidence_score,
                 status = EXCLUDED.status,
                 bot_message_id = EXCLUDED.bot_message_id,
                 daily_sequence = EXCLUDED.daily_sequence,
                 expires_at = EXCLUDED.expires_at,
                 sent_at = EXCLUDED.sent_at,
                 responded_at = EXCLUDED.responded_at,
                 response = EXCLUDED.response,
                 deferred_until = EXCLUDED.deferred_until,
                 created_at = EXCLUDED.created_at""",
            card.id,
            card.item_id,
            json.dumps(card.card_content),
            json.dumps([o.model_dump() for o in card.options]),
            card.relevance_score,
            card.confidence_score,
            card.status,
            card.bot_message_id,
            card.daily_sequence,
            card.expires_at,
            card.sent_at,
            card.responded_at,
            card.response,
            card.deferred_until,
            card.created_at,
        )
        return card

    async def update_card(self, card: TriageCard) -> None:
        await self.save_card(card)

    async def record_response(self, card_id: str, response: TriageResponse) -> None:
        await self.pool.execute(
            "UPDATE triage_cards SET status = 'responded', responded_at = $1, "
            "response = $2 WHERE id = $3",
            datetime.now(timezone.utc),
            json.dumps(response.model_dump()),
            card_id,
        )

    async def get_card(self, card_id: str) -> TriageCard | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM triage_cards WHERE id = $1", card_id
        )
        return self._row_to_card(row) if row else None

    async def get_card_by_item_id(self, item_id: str) -> TriageCard | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM triage_cards WHERE item_id = $1 AND status != 'expired' "
            "ORDER BY sent_at DESC NULLS LAST LIMIT 1",
            item_id,
        )
        return self._row_to_card(row) if row else None

    async def clear_deferral(self, card_id: str) -> None:
        await self.pool.execute(
            "UPDATE triage_cards SET deferred_until = NULL WHERE id = $1",
            card_id,
        )

    async def expire_old_cards(self, expiry_days: int) -> int:
        result = await self.pool.execute(
            "UPDATE triage_cards SET status = 'expired' "
            "WHERE status = 'queued' AND expires_at < NOW()"
        )
        # asyncpg returns e.g. "UPDATE 5"
        return int(result.split()[-1])

    async def count_sent_today(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM triage_cards " "WHERE sent_at >= CURRENT_DATE"
        )
        return row["cnt"]  # type: ignore[index]

    async def defer_card(self, card_id: str, until: datetime) -> None:
        await self.pool.execute(
            "UPDATE triage_cards SET status = 'queued', deferred_until = $1 "
            "WHERE id = $2",
            until,
            card_id,
        )

    async def get_deferred_ready(self) -> list[TriageCard]:
        rows = await self.pool.fetch(
            "SELECT * FROM triage_cards WHERE status = 'queued' "
            "AND deferred_until IS NOT NULL AND deferred_until <= NOW() "
            "ORDER BY deferred_until ASC"
        )
        return [self._row_to_card(r) for r in rows]

    async def delete_older_than(self, status: str, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM triage_cards WHERE status = $1 AND "
            "COALESCE(responded_at, sent_at, expires_at) < NOW() - INTERVAL '1 day' * $2",
            status,
            days,
        )
        return int(result.split()[-1])

    async def avg_triage_seconds(self) -> float | None:
        """Average response latency from triage_cards (ADR0040).

        AVG(EXTRACT(EPOCH FROM (responded_at - sent_at))) over cards where both
        timestamps are present. There is no ``triaged_at`` on items, so triage
        time is sourced from the card request/response pair. Returns ``None``
        when no responded cards exist.
        """
        row = await self.pool.fetchrow(
            "SELECT AVG(EXTRACT(EPOCH FROM (responded_at - sent_at))) AS avg_s "
            "FROM triage_cards "
            "WHERE responded_at IS NOT NULL AND sent_at IS NOT NULL"
        )
        return float(row["avg_s"]) if row["avg_s"] is not None else None

    @staticmethod
    def _row_to_card(row: asyncpg.Record) -> TriageCard:
        card_content = row["card_content"]
        if isinstance(card_content, str):
            card_content = json.loads(card_content)

        options_data = row["options"]
        if isinstance(options_data, str):
            options_data = json.loads(options_data)

        return TriageCard(
            id=row["id"],
            item_id=row["item_id"],
            card_content=card_content,
            options=[TriageOption(**o) for o in options_data],
            relevance_score=row["relevance_score"],
            confidence_score=row["confidence_score"],
            status=row["status"],
            bot_message_id=row["bot_message_id"],
            daily_sequence=row["daily_sequence"],
            expires_at=row["expires_at"],
            sent_at=row["sent_at"],
            responded_at=row["responded_at"],
            response=row["response"],
            deferred_until=row.get("deferred_until"),
            created_at=row["created_at"],
        )
