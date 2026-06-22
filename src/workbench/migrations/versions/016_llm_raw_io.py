"""Raw LLM I/O: persist the full request payload and raw SDK response.

Adds two nullable JSONB columns to llm_calls so the LLM Infra popup can show
the actual raw input that went into the model (model/params/system/messages/
tools) and the raw response object (content blocks, stop_reason, usage),
alongside the existing structured input/output. Nullable + no default so the
memory-subservice INSERT (which omits these columns) keeps working.

Revision ID: 016
Revises: 015
Create Date: 2026-06-22
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_calls ADD COLUMN raw_request JSONB NULL")
    op.execute("ALTER TABLE llm_calls ADD COLUMN raw_response JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS raw_response")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS raw_request")
