import pytest
from memory.queue import PendingIngestionStore
from memory.models import TriageRecordRequest, DecisionRecordRequest

TEST_DSN = "postgres://memory:memory@localhost:5432/memory"


@pytest.fixture
async def store():
    s = PendingIngestionStore(TEST_DSN)
    await s.initialize()
    await s.pool.execute("TRUNCATE pending_ingestions")
    await s.pool.execute("TRUNCATE entities")
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


# --- Entity CRUD tests ---


@pytest.mark.asyncio
async def test_upsert_entity_creates_new(store):
    await store.upsert_entity("person", "alice", {"team": "infra", "role": "tech lead"})
    entity = await store.get_entity("person", "alice")
    assert entity is not None
    assert entity["entity_type"] == "person"
    assert entity["entity_id"] == "alice"
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_upsert_entity_merges_facts(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.upsert_entity("person", "alice", {"role": "tech lead", "repos": ["infra-core"]})
    entity = await store.get_entity("person", "alice")
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"
    assert entity["facts"]["repos"] == ["infra-core"]


@pytest.mark.asyncio
async def test_upsert_entity_new_value_wins(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.upsert_entity("person", "alice", {"team": "platform"})
    entity = await store.get_entity("person", "alice")
    assert entity["facts"]["team"] == "platform"


@pytest.mark.asyncio
async def test_get_entity_not_found(store):
    entity = await store.get_entity("person", "nonexistent")
    assert entity is None


@pytest.mark.asyncio
async def test_update_graph_uuid(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.update_graph_uuid("person", "alice", "uuid-123")
    entity = await store.get_entity("person", "alice")
    assert entity["graph_uuid"] == "uuid-123"


@pytest.mark.asyncio
async def test_update_graph_uuid_overwrites(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.update_graph_uuid("person", "alice", "uuid-123")
    await store.update_graph_uuid("person", "alice", "uuid-456")
    entity = await store.get_entity("person", "alice")
    assert entity["graph_uuid"] == "uuid-456"


@pytest.mark.asyncio
async def test_clear_all_graph_uuids(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.upsert_entity("repo", "infra-core", {"language": "python"})
    await store.update_graph_uuid("person", "alice", "uuid-123")
    await store.update_graph_uuid("repo", "infra-core", "uuid-456")
    await store.clear_all_graph_uuids()
    alice = await store.get_entity("person", "alice")
    repo = await store.get_entity("repo", "infra-core")
    assert alice["graph_uuid"] is None
    assert repo["graph_uuid"] is None


# --- Type column tests ---


@pytest.mark.asyncio
async def test_enqueue_default_type_is_triage(store):
    req = TriageRecordRequest(
        card={"id": "c10", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c10", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    entries = await store.dequeue(limit=1)
    assert len(entries) == 1
    assert entries[0]["type"] == "triage"


@pytest.mark.asyncio
async def test_enqueue_with_decision_type(store):
    req = DecisionRecordRequest(
        item_summary="PR #100",
        decision="auto_include",
        reason="relevance=85",
        source_type="github",
    )
    entry_id = await store.enqueue(req, entry_type="decision")
    entries = await store.dequeue(limit=1)
    assert len(entries) == 1
    assert entries[0]["type"] == "decision"
    assert entries[0]["payload"]["item_summary"] == "PR #100"


# --- dead_letter_count tests ---


@pytest.mark.asyncio
async def test_dead_letter_count_empty(store):
    count = await store.dead_letter_count()
    assert count == 0


@pytest.mark.asyncio
async def test_dead_letter_count_after_failures(store):
    req = TriageRecordRequest(
        card={"id": "c20", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c20", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    for _ in range(3):
        await store.mark_failed(entry_id, "error")
    count = await store.dead_letter_count()
    assert count == 1
