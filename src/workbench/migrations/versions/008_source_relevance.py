"""per-source relevance/noise thresholds (B6, ADR0044).

Adds ``source_configs.relevance JSONB NULL`` holding the per-source
auto-include vs triage vs drop thresholds:

    {"auto_include_threshold": <int 0..100>,
     "triage_threshold":       <int 0..100>,
     "drop_below":             <int 0..100>}

NULL means "inherit the global PipelineConfig thresholds" (preserves current
routing for every existing source). YAML remains the source of truth (ADR0013);
this column mirrors the YAML node so the live store round-trips it.

Revision ID: 008
Revises: 007
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_configs",
        sa.Column("relevance", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_configs", "relevance")
