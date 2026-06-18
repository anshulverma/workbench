import importlib

import pytest


def test_migration_014_revision_chain():
    m = importlib.import_module("workbench.migrations.versions.014_item_lineage")
    assert m.revision == "014" and m.down_revision == "013"
    assert callable(m.upgrade) and callable(m.downgrade)


_BACKFILL = """
WITH RECURSIVE seqd AS (
    SELECT id, parent_item_id,
           row_number() OVER (PARTITION BY parent_item_id ORDER BY id) AS seq
      FROM items WHERE parent_item_id IS NOT NULL
),
tree AS (
    SELECT i.id, i.parent_item_id, NULL::smallint AS seq, i.id::text AS path
      FROM items i WHERE i.parent_item_id IS NULL
    UNION ALL
    SELECT s.id, s.parent_item_id, s.seq::smallint, t.path || '.' || s.seq AS path
      FROM seqd s JOIN tree t ON s.parent_item_id = t.id
)
UPDATE items i SET seq = tr.seq, path = tr.path
  FROM tree tr WHERE i.id = tr.id AND tr.parent_item_id IS NOT NULL
"""


async def _insert(pool, *, parent=None, source_id="x"):
    row = await pool.fetchrow(
        """INSERT INTO items
           (source_type, source_id, summary, category, origin, priority,
            status, raw_data, created_at, updated_at, parent_item_id)
           VALUES ('diff', $1, 's', 'action_item', 'manual', 'P2',
                   'active', '{}'::jsonb, NOW(), NOW(), $2)
           RETURNING id""",
        source_id,
        parent,
    )
    return row["id"]


@pytest.mark.asyncio
async def test_migration_014_backfills_three_levels(pg_pool):
    # Temporarily drop NOT NULL to simulate pre-014 state
    await pg_pool.execute("ALTER TABLE items ALTER COLUMN path DROP NOT NULL")

    seeded_ids = []
    try:
        root = await _insert(pg_pool, source_id="D-root")
        child = await _insert(pg_pool, parent=root, source_id="c1")
        grandchild = await _insert(pg_pool, parent=child, source_id="g1")
        seeded_ids = [root, child, grandchild]

        # Simulate a pre-014 state: clear the freshly-set lineage, then backfill.
        await pg_pool.execute("UPDATE items SET seq = NULL, path = NULL")
        await pg_pool.execute(
            "UPDATE items SET path = id::text WHERE parent_item_id IS NULL"
        )
        await pg_pool.execute(_BACKFILL)

        paths = {
            r["id"]: r["path"]
            for r in await pg_pool.fetch("SELECT id, path FROM items")
        }
        assert paths[root] == str(root)
        assert paths[child] == f"{root}.1"
        assert paths[grandchild] == f"{root}.1.1"
    finally:
        # Clean up seeded rows before restoring NOT NULL to prevent failures
        if seeded_ids:
            await pg_pool.execute("DELETE FROM items WHERE id = ANY($1)", seeded_ids)
        # Restore NOT NULL constraint
        await pg_pool.execute("ALTER TABLE items ALTER COLUMN path SET NOT NULL")
