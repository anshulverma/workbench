import asyncio

import pytest

TEST_DSN = "postgres://workbench:workbench@localhost:5432/workbench"

TABLES = [
    "ingestion_queue",
    "config",
    "jobs",
    "source_configs",
    "processed",
    "enrichment_trace",
    "filter_rules",
    "interaction_log",
    "triage_cards",
    "plans",
    "items",
]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def pg_pool():
    import asyncpg

    pool = await asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5)
    for table in TABLES:
        await pool.execute(f"TRUNCATE {table} CASCADE")
    yield pool
    await pool.close()


@pytest.fixture
async def stores(pg_pool):
    from workbench.storage.postgres.stores import create_postgres_stores

    s = await create_postgres_stores(TEST_DSN)
    for table in TABLES:
        await pg_pool.execute(f"TRUNCATE {table} CASCADE")
    yield s
    await s.close()
