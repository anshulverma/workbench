"""change-monitoring indexes: items(source_type, source_id), triage_cards(item_id).

Backs the stable source_id lookup (get_item_by_source_id / get_active_by_source)
and the card-by-item lookup (get_card_by_item_id) used by the change-monitoring
re-check routing and re-triage paths. Created IF NOT EXISTS for idempotency.

Revision ID: 006
Revises: 005
Create Date: 2026-06-08
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_source_lookup "
        "ON items (source_type, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_triage_cards_item_id "
        "ON triage_cards (item_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_triage_cards_item_id")
    op.execute("DROP INDEX IF EXISTS idx_items_source_lookup")
