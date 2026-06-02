"""Add choice_index column to interaction_log for rebuild support.

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interaction_log", sa.Column("choice_index", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("interaction_log", "choice_index")
