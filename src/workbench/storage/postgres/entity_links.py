from __future__ import annotations

import asyncpg

from workbench.storage.base import EntityLink, EntityLinkStore


class PgEntityLinkStore(EntityLinkStore):
    """The only reader/writer of entity_item_links.

    ``record`` / ``record_by_correlation`` resolve item paths to item ids in one
    round trip (INSERT ... SELECT ... WHERE path = ANY($paths)); an unknown path
    produces no row. Both are idempotent via the partial unique indexes
    (ON CONFLICT DO NOTHING).
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @staticmethod
    def _row(r) -> EntityLink:
        return EntityLink(
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            item_id=r["item_id"],
            item_path=r["item_path"],
            correlation_id=r["correlation_id"],
            created_at=r["created_at"],
        )

    async def record(
        self, entity_type: str, entity_id: int, item_paths: list[str]
    ) -> None:
        if not item_paths:
            return
        await self.pool.execute(
            """INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path)
               SELECT $1, $2, i.id, i.path FROM items i WHERE i.path = ANY($3::text[])
               ON CONFLICT DO NOTHING""",
            entity_type,
            entity_id,
            list(item_paths),
        )

    async def record_by_correlation(
        self, entity_type: str, correlation_id: str, item_paths: list[str]
    ) -> None:
        if not item_paths:
            return
        await self.pool.execute(
            """INSERT INTO entity_item_links
                 (entity_type, entity_id, item_id, item_path, correlation_id)
               SELECT $1, NULL, i.id, i.path, $2
                 FROM items i WHERE i.path = ANY($3::text[])
               ON CONFLICT DO NOTHING""",
            entity_type,
            correlation_id,
            list(item_paths),
        )

    async def unlink_entity(self, entity_type: str, entity_id: int) -> int:
        res = await self.pool.execute(
            "DELETE FROM entity_item_links WHERE entity_type = $1 AND entity_id = $2",
            entity_type,
            entity_id,
        )
        return int(res.split()[-1])

    async def for_item(self, path: str, *, subtree: bool = False) -> list[EntityLink]:
        if subtree:
            rows = await self.pool.fetch(
                "SELECT * FROM entity_item_links "
                "WHERE item_path = $1 OR item_path LIKE $1 || '.%' "
                "ORDER BY created_at DESC, id DESC",
                path,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM entity_item_links WHERE item_path = $1 "
                "ORDER BY created_at DESC, id DESC",
                path,
            )
        return [self._row(r) for r in rows]

    async def for_entity(self, entity_type: str, entity_id: int) -> list[EntityLink]:
        rows = await self.pool.fetch(
            "SELECT * FROM entity_item_links "
            "WHERE entity_type = $1 AND entity_id = $2 "
            "ORDER BY created_at DESC, id DESC",
            entity_type,
            entity_id,
        )
        return [self._row(r) for r in rows]
