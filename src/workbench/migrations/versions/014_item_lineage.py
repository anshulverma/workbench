"""Item lineage & stable identity: materialized path on ``items``.

Adds ``seq SMALLINT NULL`` and ``path TEXT`` (set NOT NULL after backfill),
the lineage constraints, and the path indexes (D1/D4 of the design):

  - UNIQUE(path)
  - UNIQUE(parent_item_id, seq)             -- concurrent-sibling race backstop
  - partial UNIQUE(source_type, source_id) WHERE parent_item_id IS NULL
      -- never two roots for one source thing (closes dedup gap #4)
  - B-tree on path with text_pattern_ops    -- indexed LIKE '123.%' subtree scans
  - B-tree on parent_item_id

The ``INGESTED``/``EXTRACTED`` lifecycle statuses are added at the application
layer only: ``items.status`` is a plain ``TEXT`` column (see 001_initial_schema),
not a native Postgres enum type, so no ``ALTER TYPE ... ADD VALUE`` DDL is needed
here -- the new values are accepted by the existing TEXT column as-is.

Backfill handles a non-empty DB (no-op when empty): roots get path = id::text;
children get seq = row_number() per parent and path = parent.path || '.' || seq,
applied iteratively by depth via a recursive CTE so multi-level chains resolve.

Revision ID: 014
Revises: 013
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("seq", sa.SmallInteger, nullable=True))
    op.add_column("items", sa.Column("path", sa.Text, nullable=True))

    # Backfill (no-op on an empty table). Roots first, then a recursive CTE
    # walks depth by depth so a child's path is built from its (already set)
    # parent's path.
    op.execute("UPDATE items SET path = id::text WHERE parent_item_id IS NULL")
    op.execute(
        """
        WITH RECURSIVE seqd AS (
            SELECT id, parent_item_id,
                   row_number() OVER (
                       PARTITION BY parent_item_id ORDER BY id
                   ) AS seq
              FROM items
             WHERE parent_item_id IS NOT NULL
        ),
        tree AS (
            SELECT i.id, i.parent_item_id, NULL::smallint AS seq, i.id::text AS path
              FROM items i
             WHERE i.parent_item_id IS NULL
            UNION ALL
            SELECT s.id, s.parent_item_id, s.seq::smallint,
                   t.path || '.' || s.seq AS path
              FROM seqd s
              JOIN tree t ON s.parent_item_id = t.id
        )
        UPDATE items i
           SET seq = tr.seq, path = tr.path
          FROM tree tr
         WHERE i.id = tr.id
           AND tr.parent_item_id IS NOT NULL
        """
    )

    op.alter_column("items", "path", nullable=False)

    op.create_unique_constraint("uq_items_path", "items", ["path"])
    op.create_unique_constraint(
        "uq_items_parent_seq", "items", ["parent_item_id", "seq"]
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_items_root_source "
        "ON items (source_type, source_id) WHERE parent_item_id IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_items_path_pattern " "ON items (path text_pattern_ops)"
    )
    op.create_index("idx_items_parent_item_id", "items", ["parent_item_id"])


def downgrade() -> None:
    op.drop_index("idx_items_parent_item_id", table_name="items")
    op.execute("DROP INDEX IF EXISTS idx_items_path_pattern")
    op.execute("DROP INDEX IF EXISTS uq_items_root_source")
    op.drop_constraint("uq_items_parent_seq", "items", type_="unique")
    op.drop_constraint("uq_items_path", "items", type_="unique")
    op.drop_column("items", "path")
    op.drop_column("items", "seq")
