import pytest
from memory.queue import PendingIngestionStore
from memory.models import TriageRecordRequest

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"


@pytest.fixture
async def store():
    s = PendingIngestionStore(TEST_DSN)
    await s.initialize()
    await s.pool.execute("TRUNCATE pending_ingestions")
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_enqueue_and_dequeue(store):
    req = TriageRecordRequest(
        card={"id": "c1", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c1", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    assert entry_id is not None

    entries = await store.dequeue(limit=1)
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id


@pytest.mark.asyncio
async def test_mark_completed(store):
    req = TriageRecordRequest(
        card={"id": "c2", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c2", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    await store.mark_completed(entry_id)

    entries = await store.dequeue(limit=1)
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_mark_failed_retries(store):
    req = TriageRecordRequest(
        card={"id": "c3", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c3", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    await store.mark_failed(entry_id, "test error")

    # Should be re-dequeuable after failure
    entries = await store.dequeue(limit=1)
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_dead_letter_after_max_attempts(store):
    req = TriageRecordRequest(
        card={"id": "c4", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c4", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    for _ in range(3):
        await store.mark_failed(entry_id, "error")

    entries = await store.dequeue(limit=1)
    assert len(entries) == 0

    dead = await store.get_dead_letters()
    assert len(dead) == 1


@pytest.mark.asyncio
async def test_queue_depth(store):
    req = TriageRecordRequest(
        card={"id": "c5", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c5", "choice": 1},
    )
    await store.enqueue(req)
    await store.enqueue(req)
    assert await store.queue_depth() == 2
