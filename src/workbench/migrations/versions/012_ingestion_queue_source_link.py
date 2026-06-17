"""Carry source_ref/source_url through the ingestion queue.

The source adapters set ``RawItem.source_ref`` / ``source_url`` (the clickable
"open in source" link), but the ingestion queue never persisted them, so the
worker — which rebuilds a RawItem from the queue row — dropped them and every
queued-path card lost its link. Add the two columns so they survive enqueue ->
dequeue. Nullable, so this is safe on a populated table (no wipe required).

Revision ID: 012
Revises: 011
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_queue", sa.Column("source_ref", sa.Text, nullable=True))
    op.add_column("ingestion_queue", sa.Column("source_url", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_queue", "source_url")
    op.drop_column("ingestion_queue", "source_ref")
