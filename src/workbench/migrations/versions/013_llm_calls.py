"""Create llm_calls table for LLM usage tracking.

Records every LLM call with provenance (origin/purpose/stage), token counts
(including cache read/write), batch composition, subcalls, and latency metrics.
Supports the LLM usage tracking and analytics features.

Revision ID: 013
Revises: 012
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_type", sa.Text, nullable=True),
        sa.Column("batch", sa.Integer, nullable=False, server_default="1"),
        sa.Column("items", JSONB, nullable=False, server_default="[]"),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("subcalls", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "tokens_estimated", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("is_fallback", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_index("idx_llm_calls_started_at", "llm_calls", ["started_at"])
    op.create_index("idx_llm_calls_stage_started", "llm_calls", ["stage", "started_at"])


def downgrade() -> None:
    op.drop_index("idx_llm_calls_stage_started", table_name="llm_calls")
    op.drop_index("idx_llm_calls_started_at", table_name="llm_calls")
    op.drop_table("llm_calls")
