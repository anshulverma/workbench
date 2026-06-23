"""Typed display columns on feedback_corrections + filter_tuning_tasks.

Adds the fields the UI's correction/tuning-task cards need (filter_id string,
item_summary, from/to outcomes+labels, filter_prompt, kind) so feedback can be
server-authoritative instead of client localStorage. rule_id becomes nullable on
filter_tuning_tasks (we key by the string filter_id). All adds are nullable so
existing rows/inserts keep working.

Revision ID: 017
Revises: 016
Create Date: 2026-06-22
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN filter_id TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN item_summary TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN from_label TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN to_label TEXT NULL")

    op.execute("ALTER TABLE filter_tuning_tasks ALTER COLUMN rule_id DROP NOT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN filter_id TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN item_id BIGINT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN item_summary TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN from_outcome TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN to_outcome TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN from_label TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN to_label TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN filter_prompt TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN kind TEXT NULL")


def downgrade() -> None:
    for col in ("from_label", "to_label", "item_summary", "filter_id"):
        op.execute(f"ALTER TABLE feedback_corrections DROP COLUMN IF EXISTS {col}")
    for col in (
        "kind",
        "filter_prompt",
        "to_label",
        "from_label",
        "to_outcome",
        "from_outcome",
        "item_summary",
        "item_id",
        "filter_id",
    ):
        op.execute(f"ALTER TABLE filter_tuning_tasks DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE filter_tuning_tasks ALTER COLUMN rule_id SET NOT NULL")
