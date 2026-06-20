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


async def test_entity_item_links_partial_unique_dedup(pg_pool):
    """Verify the two partial unique indexes on entity_item_links enforce deduplication.

    1. uq_eil_entity_item: (entity_type, entity_id, item_path) WHERE entity_id IS NOT NULL
    2. uq_eil_corr_item: (entity_type, correlation_id, item_path) WHERE correlation_id IS NOT NULL
    3. Sanity: correlation-only and entity-id rows for the same (entity_type, item_path) can coexist.
    """
    # Create an items row for the FK.
    item_id = await pg_pool.fetchval(
        "INSERT INTO items (source_type, source_id, summary, category, origin, "
        "priority, status, path) VALUES "
        "('t','s2','dedup_test','informational','auto_included','P2','active','9002') "
        "RETURNING id"
    )

    # Test 1: uq_eil_entity_item — two inserts with same (entity_type, entity_id, item_path)
    # where entity_id IS NOT NULL should yield exactly 1 row via ON CONFLICT DO NOTHING.
    await pg_pool.execute(
        "INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path) "
        "VALUES ('llm_call', 42, $1, '9002') ON CONFLICT DO NOTHING",
        item_id,
    )
    await pg_pool.execute(
        "INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path) "
        "VALUES ('llm_call', 42, $1, '9002') ON CONFLICT DO NOTHING",
        item_id,
    )
    count_entity = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM entity_item_links "
        "WHERE entity_type = 'llm_call' AND entity_id = 42 AND item_path = '9002'"
    )
    assert count_entity == 1, f"Expected 1 row for entity_id dedup, got {count_entity}"

    # Test 2: uq_eil_corr_item — two inserts with same (entity_type, correlation_id, item_path)
    # where correlation_id IS NOT NULL (entity_id NULL) should yield exactly 1 row.
    await pg_pool.execute(
        "INSERT INTO entity_item_links (entity_type, correlation_id, item_id, item_path) "
        "VALUES ('llm_call', 'corr-123', $1, '9002') ON CONFLICT DO NOTHING",
        item_id,
    )
    await pg_pool.execute(
        "INSERT INTO entity_item_links (entity_type, correlation_id, item_id, item_path) "
        "VALUES ('llm_call', 'corr-123', $1, '9002') ON CONFLICT DO NOTHING",
        item_id,
    )
    count_corr = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM entity_item_links "
        "WHERE entity_type = 'llm_call' AND correlation_id = 'corr-123' AND item_path = '9002'"
    )
    assert count_corr == 1, f"Expected 1 row for correlation_id dedup, got {count_corr}"

    # Test 3: Sanity — a correlation-only row and an entity-id row for the same
    # (entity_type, item_path) can coexist (partial predicates don't collide).
    total = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM entity_item_links "
        "WHERE entity_type = 'llm_call' AND item_path = '9002'"
    )
    assert (
        total == 2
    ), f"Expected 2 rows (1 entity_id, 1 correlation_id) to coexist, got {total}"

    # Cleanup
    await pg_pool.execute("DELETE FROM items WHERE id = $1", item_id)
