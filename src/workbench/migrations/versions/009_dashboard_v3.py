"""Dashboard v3 — new tables, columns, and indexes.

Creates feedback_corrections, filter_tuning_tasks, enrichers, loopbacks,
funnel_stages, funnel_order tables.  Extends filter_rules with prompt,
sources, confidence, origin, matched, enabled, label, order_index columns.
Extends items with tags, llm_summary, enriched_context, funnel_log,
verdict_action, verdict_priority, verdict_confidence columns.
Creates pg_trgm GIN index on items for full-text search.

Revision ID: 009
Revises: 008
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- pg_trgm extension (must precede GIN index) ----------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -- New tables -------------------------------------------------------
    op.create_table(
        "feedback_corrections",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, nullable=False),
        sa.Column("rule_id", sa.Text, nullable=True),
        sa.Column("original_action", sa.Text, nullable=False),
        sa.Column("corrected_action", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_feedback_corrections_item_id",
        "feedback_corrections",
        ["item_id"],
    )

    op.create_table(
        "filter_tuning_tasks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("proposed_prompt", sa.Text, nullable=False),
        sa.Column("correction_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_filter_tuning_tasks_status",
        "filter_tuning_tasks",
        ["status"],
    )

    op.create_table(
        "enrichers",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "loopbacks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("target_stage", sa.Text, nullable=False),
        sa.Column("max_iterations", sa.Integer, nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "funnel_stages",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("item_id", sa.Text, nullable=False),
        sa.Column("stage_data", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_funnel_stages_item_id", "funnel_stages", ["item_id"])

    op.create_table(
        "funnel_order",
        sa.Column("stage_id", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
    )

    # -- filter_rules new columns -----------------------------------------
    op.add_column(
        "filter_rules",
        sa.Column("prompt", sa.Text, nullable=True),
    )
    op.add_column(
        "filter_rules",
        sa.Column("sources", JSONB, nullable=True, server_default="[]"),
    )
    op.add_column(
        "filter_rules",
        sa.Column("confidence", sa.Integer, nullable=False, server_default="50"),
    )
    op.add_column(
        "filter_rules",
        sa.Column("origin", sa.Text, nullable=False, server_default="manual"),
    )
    op.add_column(
        "filter_rules",
        sa.Column("matched", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "filter_rules",
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
    )
    op.add_column(
        "filter_rules",
        sa.Column("label", sa.Text, nullable=True),
    )
    op.add_column(
        "filter_rules",
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
    )

    # Make pattern nullable (it was NOT NULL; prompt takes over)
    op.alter_column("filter_rules", "pattern", nullable=True)

    # Copy pattern -> prompt where prompt IS NULL and pattern IS NOT NULL
    op.execute(
        "UPDATE filter_rules SET prompt = pattern "
        "WHERE prompt IS NULL AND pattern IS NOT NULL"
    )

    # -- items new columns ------------------------------------------------
    op.add_column(
        "items",
        sa.Column("tags", JSONB, nullable=True, server_default="[]"),
    )
    op.add_column(
        "items",
        sa.Column("llm_summary", sa.Text, nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("enriched_context", JSONB, nullable=True, server_default="{}"),
    )
    op.add_column(
        "items",
        sa.Column("funnel_log", JSONB, nullable=True, server_default="[]"),
    )
    op.add_column(
        "items",
        sa.Column("verdict_action", sa.Text, nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("verdict_priority", sa.Text, nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("verdict_confidence", sa.Integer, nullable=True),
    )

    # -- GIN index for full-text search (pg_trgm) -------------------------
    op.execute(
        "CREATE INDEX idx_items_summary_trgm ON items "
        "USING gin (summary gin_trgm_ops)"
    )


def downgrade() -> None:
    # -- Drop GIN index ---------------------------------------------------
    op.drop_index("idx_items_summary_trgm", table_name="items")

    # -- items: drop new columns ------------------------------------------
    op.drop_column("items", "verdict_confidence")
    op.drop_column("items", "verdict_priority")
    op.drop_column("items", "verdict_action")
    op.drop_column("items", "funnel_log")
    op.drop_column("items", "enriched_context")
    op.drop_column("items", "llm_summary")
    op.drop_column("items", "tags")

    # -- filter_rules: rollback prompt -> pattern -------------------------
    op.execute(
        "UPDATE filter_rules SET pattern = prompt "
        "WHERE pattern IS NULL AND prompt IS NOT NULL"
    )

    # Restore pattern NOT NULL
    op.alter_column("filter_rules", "pattern", nullable=False)

    # Drop new columns
    op.drop_column("filter_rules", "order_index")
    op.drop_column("filter_rules", "label")
    op.drop_column("filter_rules", "enabled")
    op.drop_column("filter_rules", "matched")
    op.drop_column("filter_rules", "origin")
    op.drop_column("filter_rules", "confidence")
    op.drop_column("filter_rules", "sources")
    op.drop_column("filter_rules", "prompt")

    # -- Drop new tables --------------------------------------------------
    op.drop_table("funnel_order")
    op.drop_table("funnel_stages")
    op.drop_table("loopbacks")
    op.drop_table("enrichers")
    op.drop_table("filter_tuning_tasks")
    op.drop_table("feedback_corrections")

    # -- Drop extension ---------------------------------------------------
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
