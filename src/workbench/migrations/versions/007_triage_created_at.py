"""triage created_at: row-birth timestamp + index.

Adds ``triage_cards.created_at TIMESTAMPTZ NOT NULL DEFAULT now()`` (backfilling
existing rows with the migration timestamp) plus an index, to power the
redesigned Triage page Time-Window filter (1H/24H/7D/ALL). The queue lifecycle
is ``queued -> sent -> responded/expired``, so a card's "queued" age is exactly
its ``created_at`` -- no separate ``queued_at`` column is needed (ADR0047).

Revision ID: 007
Revises: 006
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triage_cards",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_triage_created_at", "triage_cards", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_triage_created_at", "triage_cards")
    op.drop_column("triage_cards", "created_at")
