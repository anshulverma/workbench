"""Cross-entity lineage: generic entity_item_links join table + durable messages.

Adds:
  - entity_item_links: the one bidirectional many-to-many edge table linking any
    entity (llm_call, interaction, plan, triage_card, message) to the item
    path(s) it consumed. item_id has ON DELETE CASCADE; entity_id is nullable to
    support correlation-id rows written before the async record id exists. Two
    partial unique indexes keep id-known and correlation-only rows idempotent.
  - messages: durable record per sent/received message (card, alert, briefing,
    retriage, reply) so a message is a first-class, linkable entity.
  - llm_calls.correlation_id: lets the post-persist path resolve entity_id by
    joining on this column.

Revision ID: 015
Revises: 014
Create Date: 2026-06-18
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_item_links (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_type    TEXT        NOT NULL,
            entity_id      BIGINT      NULL,
            item_id        BIGINT      NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            item_path      TEXT        NOT NULL,
            correlation_id TEXT        NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_eil_entity_item "
        "ON entity_item_links (entity_type, entity_id, item_path) "
        "WHERE entity_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_eil_corr_item "
        "ON entity_item_links (entity_type, correlation_id, item_path) "
        "WHERE correlation_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_eil_entity ON entity_item_links (entity_type, entity_id)"
    )
    op.execute(
        "CREATE INDEX idx_eil_path ON entity_item_links (item_path text_pattern_ops)"
    )
    op.execute("CREATE INDEX idx_eil_item ON entity_item_links (item_id)")
    op.execute("CREATE INDEX idx_eil_corr ON entity_item_links (correlation_id)")

    op.execute(
        """
        CREATE TABLE messages (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            kind           TEXT NOT NULL,
            direction      TEXT NOT NULL,
            bot_message_id TEXT NULL,
            body           TEXT NULL,
            summary        TEXT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute("ALTER TABLE llm_calls ADD COLUMN correlation_id TEXT NULL")
    op.execute(
        "CREATE INDEX idx_llm_calls_correlation_id ON llm_calls (correlation_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_llm_calls_correlation_id")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS correlation_id")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS entity_item_links")
