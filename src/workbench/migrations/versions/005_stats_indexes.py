"""stats indexes: items(source_type), items(status), ingestion_queue(status).

Btree indexes backing the COUNT(*) GROUP BY aggregation methods used by the
Stats & aggregation API (/api/stats/*). Created IF NOT EXISTS so the migration
is idempotent against any pre-existing indexes.

Revision ID: 005
Revises: 004
Create Date: 2026-06-06
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_items_source_type ON items (source_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_items_status ON items (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ingestion_queue_status "
        "ON ingestion_queue (status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingestion_queue_status")
    op.execute("DROP INDEX IF EXISTS ix_items_status")
    op.execute("DROP INDEX IF EXISTS ix_items_source_type")
