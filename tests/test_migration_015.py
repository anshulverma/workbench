"""Round-trip schema test for migration 015 (entity_item_links + messages).

Assumes `alembic upgrade head` has been run so the schema is at 015. Verifies
the new tables, the llm_calls.correlation_id column, and the six entity_item_links
indexes exist, and that an entity_item_links row round-trips with an items FK.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_entity_item_links_table_and_indexes(pg_pool):
    cols = {
        r["column_name"]: r["is_nullable"]
        for r in await pg_pool.fetch(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'entity_item_links'"
        )
    }
    assert cols["entity_type"] == "NO"
    assert cols["entity_id"] == "YES"
    assert cols["item_id"] == "NO"
    assert cols["item_path"] == "NO"
    assert cols["correlation_id"] == "YES"

    idx = {
        r["indexname"]
        for r in await pg_pool.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'entity_item_links'"
        )
    }
    for name in (
        "uq_eil_entity_item",
        "uq_eil_corr_item",
        "idx_eil_entity",
        "idx_eil_path",
        "idx_eil_item",
        "idx_eil_corr",
    ):
        assert name in idx, f"missing index {name}"


async def test_messages_table(pg_pool):
    cols = {
        r["column_name"]
        for r in await pg_pool.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'messages'"
        )
    }
    assert {
        "id",
        "kind",
        "direction",
        "bot_message_id",
        "body",
        "summary",
        "created_at",
    } <= cols


async def test_llm_calls_correlation_id_column(pg_pool):
    cols = {
        r["column_name"]
        for r in await pg_pool.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'llm_calls'"
        )
    }
    assert "correlation_id" in cols


async def test_entity_item_links_roundtrip_and_cascade(pg_pool):
    item_id = await pg_pool.fetchval(
        "INSERT INTO items (source_type, source_id, summary, category, origin, "
        "priority, status, path) VALUES "
        "('t','s1','sum','informational','auto_included','P2','active','9001') "
        "RETURNING id"
    )
    link_id = await pg_pool.fetchval(
        "INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path) "
        "VALUES ('llm_call', 1, $1, '9001') RETURNING id",
        item_id,
    )
    assert link_id is not None
    # ON DELETE CASCADE: deleting the item removes the link row.
    await pg_pool.execute("DELETE FROM items WHERE id = $1", item_id)
    remaining = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM entity_item_links WHERE id = $1", link_id
    )
    assert remaining == 0
