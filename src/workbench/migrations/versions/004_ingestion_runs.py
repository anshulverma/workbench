"""ingestion_runs table.

Revision ID: 004
Revises: 003
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("raw_enqueued", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_ingestion_runs_source_started",
        "ingestion_runs",
        ["source_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_source_started", "ingestion_runs")
    op.drop_table("ingestion_runs")
