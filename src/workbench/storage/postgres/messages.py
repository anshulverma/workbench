from __future__ import annotations

import asyncpg

from workbench.domain.messages import Message
from workbench.storage.base import MessageStore


class PgMessageStore(MessageStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @staticmethod
    def _row(r) -> Message:
        return Message(
            id=r["id"],
            kind=r["kind"],
            direction=r["direction"],
            bot_message_id=r["bot_message_id"],
            body=r["body"],
            summary=r["summary"],
            created_at=r["created_at"],
        )

    async def save(self, message: Message) -> Message:
        row = await self.pool.fetchrow(
            """INSERT INTO messages (kind, direction, bot_message_id, body, summary)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, kind, direction, bot_message_id, body, summary, created_at""",
            message.kind,
            message.direction,
            message.bot_message_id,
            message.body,
            message.summary,
        )
        return self._row(row)

    async def get_by_id(self, message_id: int) -> Message | None:
        r = await self.pool.fetchrow("SELECT * FROM messages WHERE id = $1", message_id)
        return self._row(r) if r else None

    async def list_recent(self, limit: int) -> list[Message]:
        rows = await self.pool.fetch(
            "SELECT * FROM messages ORDER BY created_at DESC, id DESC LIMIT $1", limit
        )
        return [self._row(r) for r in rows]

    async def delete_older_than(self, days: int, *, entity_links=None) -> int:
        # Cascade-unlink message entity links before deleting the rows; the
        # entity side has no DB FK, so dangling entity_item_links rows would
        # otherwise survive the prune (mirrors the llm_calls pruners).
        if entity_links is not None:
            ids = await self.pool.fetch(
                "SELECT id FROM messages WHERE created_at < NOW() - INTERVAL '1 day' * $1",
                days,
            )
            for row in ids:
                await entity_links.unlink_entity("message", row["id"])
        res = await self.pool.execute(
            "DELETE FROM messages WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(res.split()[-1])
