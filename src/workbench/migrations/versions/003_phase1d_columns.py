"""phase1d: deferred_until, action fields, interaction fields.

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("triage_cards", sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True))

    op.add_column("items", sa.Column("parent_item_id", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_source", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("action_category", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_items_action_source", "items", ["action_source"], postgresql_where=sa.text("action_source IS NOT NULL"))

    op.execute("""
        CREATE TABLE adapter_state (
            adapter_name TEXT PRIMARY KEY,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.add_column("interaction_log", sa.Column("type", sa.Text(), nullable=True))
    op.add_column("interaction_log", sa.Column("interpreted", JSONB, nullable=True))
    op.add_column("interaction_log", sa.Column("confirmed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS adapter_state")
    op.drop_column("interaction_log", "confirmed")
    op.drop_column("interaction_log", "interpreted")
    op.drop_column("interaction_log", "type")
    op.drop_index("idx_items_action_source", "items")
    op.drop_column("items", "completed_at")
    op.drop_column("items", "snoozed_until")
    op.drop_column("items", "action_category")
    op.drop_column("items", "action_source")
    op.drop_column("items", "parent_item_id")
    op.drop_column("triage_cards", "deferred_until")
