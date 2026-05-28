"""Initial schema — all tables for Phase 1a.

Revision ID: 001
Revises: None
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("raw_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_items_status_priority", "items", ["status", "priority"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("sources", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "triage_cards",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text),
        sa.Column("card_content", JSONB, nullable=False, server_default="{}"),
        sa.Column("options", JSONB, nullable=False, server_default="[]"),
        sa.Column("relevance_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("confidence_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("bot_message_id", sa.Text),
        sa.Column("daily_sequence", sa.Integer),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("response", sa.Text),
    )
    op.create_index("idx_triage_status", "triage_cards", ["status"])
    op.create_index("idx_triage_relevance", "triage_cards", ["relevance_score"])

    op.create_table(
        "interaction_log",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("item_id", sa.Text),
        sa.Column("item_summary", sa.Text, nullable=False),
        sa.Column("triage_card_full", JSONB, nullable=False, server_default="{}"),
        sa.Column("enrichment_context", JSONB, nullable=False, server_default="{}"),
        sa.Column("options_presented", JSONB, nullable=False, server_default="[]"),
        sa.Column("option_chosen", sa.Text, nullable=False, server_default=""),
        sa.Column("todo_created", JSONB),
        sa.Column("enrichment_depth", sa.Text, nullable=False, server_default="none"),
        sa.Column("enrichment_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enrichment_time_ms", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "filter_rules",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_type", sa.Text),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("priority", sa.Text),
        sa.Column("created_from_interaction_id", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "enrichment_trace",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, nullable=False),
        sa.Column("depth", sa.Text, nullable=False),
        sa.Column("calls_made", sa.Integer, nullable=False),
        sa.Column("time_ms", sa.Integer, nullable=False),
        sa.Column("context_retrieved", JSONB, nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "processed",
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("source_type", "source_id"),
    )

    op.create_table(
        "source_configs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("adapter_type", sa.Text, nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("schedule", sa.Text, nullable=False, server_default="*/15 * * * *"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("input_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("items_extracted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_included", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_triaged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_dropped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "config",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )

    op.create_table(
        "ingestion_queue",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("raw_content", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text),
        sa.Column("urgency_signals", JSONB, nullable=False, server_default="{}"),
        sa.Column("urgency_score", sa.Integer, nullable=False),
        sa.Column("job_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_iq_status_urgency", "ingestion_queue", ["status", "urgency_score"])
    op.create_index("idx_iq_next_retry", "ingestion_queue", ["next_retry_at"])


def downgrade() -> None:
    for table in ["ingestion_queue", "config", "jobs", "source_configs", "processed",
                  "enrichment_trace", "filter_rules", "interaction_log", "triage_cards",
                  "plans", "items"]:
        op.drop_table(table)
