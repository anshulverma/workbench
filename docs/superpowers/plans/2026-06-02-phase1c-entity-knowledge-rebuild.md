# Phase 1c: Entity Knowledge, Decision Recording, and Memory Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in the four 501-stub memory service endpoints (entity recording, decision recording, entity querying, relationship querying), add admin endpoints, wire entity/relationship context into the pipeline's noise filter and enricher, update triage recording to support rebuild, and add a CLI rebuild script.

**Architecture:** Dual-storage for entities (PostgreSQL for fast key-value lookups, Neo4j graph for relationship traversal). Decision recording uses the same two-layer pattern as triage (deterministic structured edge + LLM episode extraction). Pipeline integration queries entity/relationship context in parallel with preference facts in the noise filter, and the enricher queries/records entities via the memory layer. A CLI script reconstructs the knowledge graph by replaying the interaction log.

**Tech Stack:** Python, FastAPI, asyncpg, Graphiti (Neo4j), Pydantic, Alembic, pytest

---

### Task 1: Memory Service Models

**Files:**
- Modify: `src/memory/memory/models.py`
- Test: `src/memory/tests/test_models.py`

- [ ] **Step 1: Write failing tests for new models**

```python
# Append to src/memory/tests/test_models.py

from memory.models import (
    EntityRecordRequest,
    DecisionRecordRequest,
    EntityResponse,
    RelationshipsResponse,
    QueueDepthResponse,
)


def test_entity_record_request():
    req = EntityRecordRequest(
        entity_type="person", entity_id="alice", facts={"team": "infra"}
    )
    assert req.entity_type == "person"
    assert req.entity_id == "alice"
    assert req.facts == {"team": "infra"}


def test_entity_record_request_requires_fields():
    import pytest
    with pytest.raises(Exception):
        EntityRecordRequest(entity_type="person")


def test_decision_record_request():
    req = DecisionRecordRequest(
        item_summary="PR #100", decision="auto_include", reason="relevance=85"
    )
    assert req.source_type == "unknown"


def test_decision_record_request_with_source():
    req = DecisionRecordRequest(
        item_summary="PR #100", decision="auto_include",
        reason="relevance=85", source_type="github",
    )
    assert req.source_type == "github"


def test_entity_response():
    resp = EntityResponse(
        entity_type="person", entity_id="alice", facts={"team": "infra"}
    )
    assert resp.entity_type == "person"


def test_relationships_response_empty():
    resp = RelationshipsResponse(relationships=[])
    assert resp.relationships == []


def test_relationships_response_with_data():
    resp = RelationshipsResponse(relationships=[
        {"from_entity": "alice", "to_entity": "infra-core", "relation": "reviews"}
    ])
    assert len(resp.relationships) == 1


def test_queue_depth_response():
    resp = QueueDepthResponse(depth=5, dead_letters=1)
    assert resp.depth == 5
    assert resp.dead_letters == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_models.py -v --tb=short -k "entity_record or decision_record or entity_response or relationships_response or queue_depth"`
Expected: ImportError — models don't exist yet

- [ ] **Step 3: Add the five new models**

```python
# Append to src/memory/memory/models.py


class EntityRecordRequest(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict


class DecisionRecordRequest(BaseModel):
    item_summary: str
    decision: str
    reason: str
    source_type: str = "unknown"


class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict


class RelationshipsResponse(BaseModel):
    relationships: list[dict] = Field(default_factory=list)


class QueueDepthResponse(BaseModel):
    depth: int
    dead_letters: int
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_models.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/memory/memory/models.py src/memory/tests/test_models.py
git commit -m "feat(memory): add entity/decision/relationship/queue-depth models"
```

---

### Task 2: Entities Table and Queue Type Column

**Files:**
- Modify: `src/memory/memory/queue.py`
- Test: `src/memory/tests/test_queue.py`

- [ ] **Step 1: Write failing tests for entity CRUD**

```python
# Append to src/memory/tests/test_queue.py


@pytest.mark.asyncio
async def test_upsert_entity_creates_new(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    entity = await store.get_entity("person", "alice")
    assert entity is not None
    assert entity["facts"]["team"] == "infra"


@pytest.mark.asyncio
async def test_upsert_entity_merges_facts(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.upsert_entity("person", "alice", {"role": "tech lead"})
    entity = await store.get_entity("person", "alice")
    assert entity["facts"]["team"] == "infra"
    assert entity["facts"]["role"] == "tech lead"


@pytest.mark.asyncio
async def test_upsert_entity_overwrites_existing_key(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.upsert_entity("person", "alice", {"team": "platform"})
    entity = await store.get_entity("person", "alice")
    assert entity["facts"]["team"] == "platform"


@pytest.mark.asyncio
async def test_get_entity_not_found(store):
    entity = await store.get_entity("person", "unknown")
    assert entity is None


@pytest.mark.asyncio
async def test_update_graph_uuid(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.update_graph_uuid("person", "alice", "uuid-123")
    entity = await store.get_entity("person", "alice")
    assert entity["graph_uuid"] == "uuid-123"


@pytest.mark.asyncio
async def test_clear_all_graph_uuids(store):
    await store.upsert_entity("person", "alice", {"team": "infra"})
    await store.update_graph_uuid("person", "alice", "uuid-123")
    await store.clear_all_graph_uuids()
    entity = await store.get_entity("person", "alice")
    assert entity["graph_uuid"] is None


@pytest.mark.asyncio
async def test_enqueue_with_type(store):
    from memory.models import TriageRecordRequest
    req = TriageRecordRequest(
        card={"id": "c10", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c10", "choice": 1},
    )
    entry_id = await store.enqueue(req, entry_type="decision")
    entries = await store.dequeue(limit=1)
    assert len(entries) == 1
    assert entries[0]["type"] == "decision"


@pytest.mark.asyncio
async def test_dead_letter_count(store):
    from memory.models import TriageRecordRequest
    req = TriageRecordRequest(
        card={"id": "c11", "card_content": {"summary": "test"}, "options": [], "relevance_score": 50},
        response={"card_id": "c11", "choice": 1},
    )
    entry_id = await store.enqueue(req)
    for _ in range(3):
        await store.mark_failed(entry_id, "error")
    count = await store.dead_letter_count()
    assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_queue.py -v --tb=short -k "entity or graph_uuid or enqueue_with_type or dead_letter_count"`
Expected: AttributeError — methods don't exist yet

- [ ] **Step 3: Update CREATE_TABLE and add entities table, update methods**

Replace the `CREATE_TABLE` constant and update the `PendingIngestionStore` class in `src/memory/memory/queue.py`:

```python
# Replace CREATE_TABLE with:
CREATE_PENDING_TABLE = """
CREATE TABLE IF NOT EXISTS pending_ingestions (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'triage',
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_ENTITIES_TABLE = """
CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    facts JSONB NOT NULL DEFAULT '{}',
    graph_uuid TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, entity_id)
)
"""
```

Update `initialize()`:
```python
    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(CREATE_PENDING_TABLE)
        await self.pool.execute(CREATE_ENTITIES_TABLE)
```

Update `enqueue()` to accept `entry_type`:
```python
    async def enqueue(self, request: TriageRecordRequest, entry_type: str = "triage") -> str:
        entry_id = str(uuid.uuid4())
        payload = request.model_dump_json()
        await self.pool.execute(
            "INSERT INTO pending_ingestions (id, type, payload, max_attempts) VALUES ($1, $2, $3::jsonb, $4)",
            entry_id, entry_type, payload, self.max_attempts,
        )
        return entry_id
```

Update `dequeue()` RETURNING clause to include `type`:
```python
    async def dequeue(self, limit: int = 1) -> list[dict]:
        rows = await self.pool.fetch(
            """
            UPDATE pending_ingestions
            SET status = 'processing', updated_at = NOW()
            WHERE id IN (
                SELECT id FROM pending_ingestions
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, type, payload, attempt
            """,
            limit,
        )
        return [{"id": r["id"], "type": r["type"], "payload": json.loads(r["payload"]), "attempt": r["attempt"]} for r in rows]
```

Add entity CRUD methods:
```python
    async def upsert_entity(self, entity_type: str, entity_id: str, facts: dict) -> None:
        facts_json = json.dumps(facts)
        await self.pool.execute(
            """
            INSERT INTO entities (entity_type, entity_id, facts)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (entity_type, entity_id)
            DO UPDATE SET facts = entities.facts || $3::jsonb, updated_at = NOW()
            """,
            entity_type, entity_id, facts_json,
        )

    async def get_entity(self, entity_type: str, entity_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT entity_type, entity_id, facts, graph_uuid, created_at, updated_at FROM entities WHERE entity_type = $1 AND entity_id = $2",
            entity_type, entity_id,
        )
        if not row:
            return None
        return {
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "facts": json.loads(row["facts"]) if isinstance(row["facts"], str) else row["facts"],
            "graph_uuid": row["graph_uuid"],
        }

    async def update_graph_uuid(self, entity_type: str, entity_id: str, graph_uuid: str) -> None:
        await self.pool.execute(
            "UPDATE entities SET graph_uuid = $1, updated_at = NOW() WHERE entity_type = $2 AND entity_id = $3",
            graph_uuid, entity_type, entity_id,
        )

    async def clear_all_graph_uuids(self) -> None:
        await self.pool.execute("UPDATE entities SET graph_uuid = NULL, updated_at = NOW()")

    async def dead_letter_count(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as count FROM pending_ingestions WHERE status = 'dead_letter'"
        )
        return row["count"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_queue.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/memory/memory/queue.py src/memory/tests/test_queue.py
git commit -m "feat(memory): add entities table and queue type column"
```

---

### Task 3: Decision Extraction Prompt and Narrative Formatter

**Files:**
- Modify: `src/memory/memory/extraction.py`
- Test: `src/memory/tests/test_extraction.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to src/memory/tests/test_extraction.py

from memory.extraction import DECISION_EXTRACTION_PROMPT, format_decision_narrative


def test_decision_extraction_prompt_exists():
    assert "pipeline" in DECISION_EXTRACTION_PROMPT.lower()
    assert "includes" in DECISION_EXTRACTION_PROMPT.lower()
    assert "drops" in DECISION_EXTRACTION_PROMPT.lower()


def test_format_decision_narrative_auto_include():
    narrative = format_decision_narrative(
        item_summary="PR #100 rate limiting",
        decision="auto_include",
        reason="relevance=85",
        source_type="github",
    )
    assert "auto_include" in narrative
    assert "PR #100 rate limiting" in narrative
    assert "github" in narrative
    assert "relevance=85" in narrative


def test_format_decision_narrative_auto_drop():
    narrative = format_decision_narrative(
        item_summary="CI bot notification",
        decision="auto_drop",
        reason="relevance=10",
        source_type="github",
    )
    assert "auto_drop" in narrative
    assert "CI bot notification" in narrative
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_extraction.py -v --tb=short -k "decision"`
Expected: ImportError

- [ ] **Step 3: Add prompt and formatter**

```python
# Append to src/memory/memory/extraction.py

DECISION_EXTRACTION_PROMPT = """You are extracting patterns about pipeline filtering decisions.
Focus on:
- What types of items the pipeline consistently includes or drops
- Source types, topics, or patterns that predict inclusion/exclusion
- Threshold behaviors (items near the relevance cutoff)

Extract facts in the form: "Pipeline [always/never/usually] [includes/drops] [item pattern] [when condition]"
"""


def format_decision_narrative(
    item_summary: str, decision: str, reason: str, source_type: str
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return f"""Pipeline decision at {now}:
Source type: {source_type}
Item summary: "{item_summary}"
Decision: {decision}
Reason: {reason}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_extraction.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/memory/memory/extraction.py src/memory/tests/test_extraction.py
git commit -m "feat(memory): add decision extraction prompt and narrative formatter"
```

---

### Task 4: GraphitiMemoryLayer — Entity Methods

**Files:**
- Modify: `src/memory/memory/graphiti_layer.py`
- Test: `src/memory/tests/test_graphiti_layer.py`

- [ ] **Step 1: Write failing tests for record_entity and query_entity**

```python
# Append to src/memory/tests/test_graphiti_layer.py


@pytest.mark.asyncio
async def test_record_entity_calls_add_triplet_per_fact(layer, mock_graphiti):
    mock_graphiti.add_triplet.return_value = MagicMock(
        source_node=MagicMock(uuid="resolved-uuid-1"),
    )

    await layer.record_entity(
        "person", "alice", {"team": "infra", "role": "tech lead"},
        store=None,
    )

    assert mock_graphiti.add_triplet.call_count == 2


@pytest.mark.asyncio
async def test_record_entity_uses_entity_as_source_node(layer, mock_graphiti):
    mock_graphiti.add_triplet.return_value = MagicMock(
        source_node=MagicMock(uuid="resolved-uuid"),
    )

    await layer.record_entity(
        "person", "alice", {"team": "infra"},
        store=None,
    )

    call_args = mock_graphiti.add_triplet.call_args
    source_node = call_args.args[0]
    assert source_node.name == "person:alice"


@pytest.mark.asyncio
async def test_record_entity_updates_graph_uuid_in_store(layer, mock_graphiti):
    mock_graphiti.add_triplet.return_value = MagicMock(
        source_node=MagicMock(uuid="resolved-uuid-42"),
    )
    mock_store = AsyncMock()

    await layer.record_entity(
        "person", "alice", {"team": "infra"},
        store=mock_store,
    )

    mock_store.update_graph_uuid.assert_called_with("person", "alice", "resolved-uuid-42")


@pytest.mark.asyncio
async def test_query_entity_reads_from_store(layer):
    mock_store = AsyncMock()
    mock_store.get_entity.return_value = {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {"team": "infra"},
        "graph_uuid": "uuid-1",
    }

    result = await layer.query_entity("person", "alice", store=mock_store)

    assert result is not None
    assert result["entity_type"] == "person"
    assert result["facts"]["team"] == "infra"


@pytest.mark.asyncio
async def test_query_entity_not_found(layer):
    mock_store = AsyncMock()
    mock_store.get_entity.return_value = None

    result = await layer.query_entity("person", "unknown", store=mock_store)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short -k "record_entity or query_entity"`
Expected: AttributeError — methods don't exist

- [ ] **Step 3: Implement record_entity and query_entity**

Add these methods to `GraphitiMemoryLayer` in `src/memory/memory/graphiti_layer.py`:

```python
    async def record_entity(
        self, entity_type: str, entity_id: str, facts: dict,
        store: "PendingIngestionStore | None",
    ) -> None:
        from graphiti_core.nodes import EntityNode
        from graphiti_core.edges import EntityEdge

        entity_name = f"{entity_type}:{entity_id}"
        resolved_uuid = None

        # Graph writes first — if any fail, exception propagates and PG is never written
        for key, value in facts.items():
            source_node = EntityNode(
                uuid=str(uuid4()),
                name=entity_name,
                labels=[entity_type.capitalize()],
                group_id="workbench",
            )
            target_node = EntityNode(
                uuid=str(uuid4()),
                name=str(value),
                labels=["Fact"],
                attributes={"key": key},
                group_id="workbench",
            )
            edge = EntityEdge(
                uuid=str(uuid4()),
                name=f"has_fact {key}",
                fact=f"{entity_name} has {key}: {value}",
                source_node_uuid=source_node.uuid,
                target_node_uuid=target_node.uuid,
                created_at=datetime.now(timezone.utc),
                group_id="workbench",
            )

            result = await self.graphiti.add_triplet(source_node, edge, target_node)
            resolved_uuid = result.source_node.uuid

        # PG writes only after all graph writes succeed (atomicity per spec)
        if store:
            await store.upsert_entity(entity_type, entity_id, facts)
            if resolved_uuid:
                await store.update_graph_uuid(entity_type, entity_id, resolved_uuid)

    async def query_entity(
        self, entity_type: str, entity_id: str,
        store: "PendingIngestionStore | None",
    ) -> dict | None:
        if not store:
            return None
        return await store.get_entity(entity_type, entity_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/memory/memory/graphiti_layer.py src/memory/tests/test_graphiti_layer.py
git commit -m "feat(memory): implement record_entity and query_entity in GraphitiMemoryLayer"
```

---

### Task 5: GraphitiMemoryLayer — Decision Recording and Relationship Querying

**Files:**
- Modify: `src/memory/memory/graphiti_layer.py`
- Test: `src/memory/tests/test_graphiti_layer.py`

- [ ] **Step 1: Write failing tests for record_decision**

```python
# Append to src/memory/tests/test_graphiti_layer.py


@pytest.mark.asyncio
async def test_record_decision_creates_structured_edge(layer, mock_graphiti):
    await layer.record_decision(
        item_summary="PR #100 rate limiting",
        decision="auto_include",
        reason="relevance=85",
        source_type="github",
    )

    mock_graphiti.add_triplet.assert_called_once()
    call_args = mock_graphiti.add_triplet.call_args
    source_node = call_args.args[0]
    edge = call_args.args[1]
    assert source_node.name == "pipeline"
    assert "included" in edge.name


@pytest.mark.asyncio
async def test_record_decision_drop_edge(layer, mock_graphiti):
    await layer.record_decision(
        item_summary="CI bot notification",
        decision="auto_drop",
        reason="relevance=10",
        source_type="github",
    )

    call_args = mock_graphiti.add_triplet.call_args
    edge = call_args.args[1]
    assert "dropped" in edge.name


@pytest.mark.asyncio
async def test_record_decision_calls_add_episode(layer, mock_graphiti):
    await layer.record_decision(
        item_summary="PR #100 rate limiting",
        decision="auto_include",
        reason="relevance=85",
        source_type="github",
    )

    mock_graphiti.add_episode.assert_called_once()
    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert "PR #100" in call_kwargs["episode_body"]
    assert "pipeline" in call_kwargs["custom_extraction_instructions"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short -k "record_decision"`
Expected: AttributeError

- [ ] **Step 3: Implement record_decision**

```python
    async def record_decision(
        self, item_summary: str, decision: str, reason: str, source_type: str
    ) -> None:
        from graphiti_core.nodes import EntityNode, EpisodeType
        from graphiti_core.edges import EntityEdge
        from memory.extraction import DECISION_EXTRACTION_PROMPT, format_decision_narrative

        edge_name = "included" if decision == "auto_include" else "dropped"

        pipeline_node = EntityNode(
            uuid=str(uuid4()),
            name="pipeline",
            labels=["Pipeline"],
            group_id="workbench",
        )
        pattern_node = EntityNode(
            uuid=str(uuid4()),
            name=item_summary,
            labels=["Pattern"],
            attributes={"source_type": source_type},
            group_id="workbench",
        )
        edge = EntityEdge(
            uuid=str(uuid4()),
            name=edge_name,
            fact=f"Pipeline {edge_name} items like: {item_summary}",
            source_node_uuid=pipeline_node.uuid,
            target_node_uuid=pattern_node.uuid,
            created_at=datetime.now(timezone.utc),
            attributes={"reason": reason, "source_type": source_type},
            group_id="workbench",
        )

        await self.graphiti.add_triplet(pipeline_node, edge, pattern_node)

        narrative = format_decision_narrative(item_summary, decision, reason, source_type)
        await self.graphiti.add_episode(
            name=f"decision-{uuid4()}",
            episode_body=narrative,
            source_description="workbench pipeline decision",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            custom_extraction_instructions=DECISION_EXTRACTION_PROMPT,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short -k "record_decision"`
Expected: All pass

- [ ] **Step 5: Write failing tests for query_relationships**

```python
# Append to src/memory/tests/test_graphiti_layer.py


@pytest.mark.asyncio
async def test_query_relationships_by_graph_uuid(layer, mock_graphiti):
    mock_store = AsyncMock()
    mock_store.get_entity.return_value = {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {"team": "infra"},
        "graph_uuid": "uuid-42",
    }

    mock_result = [
        {"from_entity": "alice", "to_entity": "infra-core", "relation": "reviews", "fact": "alice reviews infra-core"},
    ]
    mock_graphiti.driver.execute_query = AsyncMock(return_value=(mock_result, None, None))

    rels = await layer.query_relationships("person", "alice", store=mock_store)

    assert len(rels) == 1
    assert rels[0]["from_entity"] == "alice"
    assert rels[0]["to_entity"] == "infra-core"
    assert rels[0]["relation"] == "reviews"


@pytest.mark.asyncio
async def test_query_relationships_no_graph_uuid(layer, mock_graphiti):
    mock_store = AsyncMock()
    mock_store.get_entity.return_value = {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {},
        "graph_uuid": None,
    }

    rels = await layer.query_relationships("person", "alice", store=mock_store)
    assert rels == []


@pytest.mark.asyncio
async def test_query_relationships_entity_not_found(layer, mock_graphiti):
    mock_store = AsyncMock()
    mock_store.get_entity.return_value = None

    rels = await layer.query_relationships("person", "unknown", store=mock_store)
    assert rels == []
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short -k "query_relationships"`
Expected: AttributeError

- [ ] **Step 7: Implement query_relationships**

```python
    async def query_relationships(
        self, entity_type: str, entity_id: str,
        store: "PendingIngestionStore | None",
    ) -> list[dict]:
        if not store:
            return []

        entity = await store.get_entity(entity_type, entity_id)
        if not entity or not entity.get("graph_uuid"):
            return []

        graph_uuid = entity["graph_uuid"]
        try:
            query = """
            MATCH (n:Entity {uuid: $uuid})-[e:RELATES_TO]-(m:Entity)
            RETURN n.name AS from_entity, m.name AS to_entity, e.name AS relation, e.fact AS fact
            """
            records, _, _ = await self.graphiti.driver.execute_query(
                query, uuid=graph_uuid,
            )
            return [
                {
                    "from_entity": r["from_entity"],
                    "to_entity": r["to_entity"],
                    "relation": r["relation"],
                }
                for r in records
            ]
        except Exception as e:
            logger.error("Failed to query relationships: %s", e, exc_info=True)
            return []
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_graphiti_layer.py -v --tb=short`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/memory/memory/graphiti_layer.py src/memory/tests/test_graphiti_layer.py
git commit -m "feat(memory): implement record_decision and query_relationships"
```

---

### Task 6: Memory Service Endpoints and Worker Dispatch

**Files:**
- Modify: `src/memory/memory/main.py`
- Modify: `src/memory/memory/models.py` (import)

- [ ] **Step 1: Update imports in main.py**

Add new model imports to the existing import block:

```python
from memory.models import (
    DecisionRecordRequest,
    EntityRecordRequest,
    EntityResponse,
    FactsListResponse,
    HealthResponse,
    PreferenceQueryResponse,
    QueueDepthResponse,
    RelationshipsResponse,
    TriageRecordRequest,
)
```

- [ ] **Step 2: Replace the four 501 stubs with real endpoints**

Replace the four stub route definitions at the end of `create_app()` (lines 169-183) with:

```python
    @app.post("/record/entity", status_code=200)
    async def record_entity(request: EntityRecordRequest):
        layer: GraphitiMemoryLayer = app.state.layer
        store: PendingIngestionStore = app.state.store
        # record_entity does graph writes first, then PG upsert + graph_uuid update.
        # If graph fails, PG is never written (atomicity per spec).
        await layer.record_entity(
            request.entity_type, request.entity_id, request.facts, store=store,
        )
        return {"status": "recorded"}

    @app.post("/record/decision", status_code=202)
    async def record_decision(request: DecisionRecordRequest):
        store: PendingIngestionStore = app.state.store
        entry_id = await store.enqueue(request, entry_type="decision")
        return {"status": "queued", "entry_id": entry_id}

    @app.get("/query/entity", response_model=EntityResponse)
    async def query_entity(entity_type: str = Query(...), entity_id: str = Query(...)):
        from fastapi import HTTPException
        store: PendingIngestionStore = app.state.store
        entity = await store.get_entity(entity_type, entity_id)
        if not entity:
            raise HTTPException(404, "Entity not found")
        return EntityResponse(
            entity_type=entity["entity_type"],
            entity_id=entity["entity_id"],
            facts=entity["facts"],
        )

    @app.get("/query/relationships", response_model=RelationshipsResponse)
    async def query_relationships(
        entity_type: str = Query(...), entity_id: str = Query(...),
    ):
        layer: GraphitiMemoryLayer = app.state.layer
        store: PendingIngestionStore = app.state.store
        rels = await layer.query_relationships(entity_type, entity_id, store=store)
        return RelationshipsResponse(relationships=rels)
```

- [ ] **Step 3: Add admin endpoints**

```python
    @app.post("/admin/reset-graph", status_code=200)
    async def reset_graph():
        import os
        if os.environ.get("MEMORY_ADMIN_ENABLED", "").lower() != "true":
            from fastapi import HTTPException
            raise HTTPException(403, "Admin endpoints disabled")
        graphiti = app.state.graphiti
        store: PendingIngestionStore = app.state.store
        await graphiti.driver.execute_query("MATCH (n) DETACH DELETE n")
        await store.clear_all_graph_uuids()
        return {"status": "reset"}

    @app.get("/admin/queue-depth", response_model=QueueDepthResponse)
    async def queue_depth():
        store: PendingIngestionStore = app.state.store
        depth = await store.queue_depth()
        dead = await store.dead_letter_count()
        return QueueDepthResponse(depth=depth, dead_letters=dead)
```

- [ ] **Step 4: Update worker dispatch to handle decision type**

Replace the `process` inner function in `_run_ingestion_worker`:

```python
            async def process(entry):
                async with semaphore:
                    try:
                        payload = entry["payload"]
                        entry_type = entry.get("type", "triage")
                        if entry_type == "decision":
                            await layer.record_decision(
                                item_summary=payload["item_summary"],
                                decision=payload["decision"],
                                reason=payload["reason"],
                                source_type=payload.get("source_type", "unknown"),
                            )
                        else:
                            await layer.record_triage(payload["card"], payload["response"])
                        await store.mark_completed(entry["id"])
                        logger.info("Ingestion completed for %s entry %s", entry_type, entry["id"])
                    except Exception as e:
                        logger.error("Ingestion failed for entry %s: %s", entry["id"], e)
                        await store.mark_failed(entry["id"], str(e))
```

- [ ] **Step 5: Run all memory service tests**

Run: `cd src/memory && python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/memory/memory/main.py
git commit -m "feat(memory): replace 501 stubs with real endpoints, add admin endpoints"
```

---

### Task 7: Workbench MemoryLayer ABC and Model Changes

**Files:**
- Modify: `src/workbench/memory/base.py`
- Modify: `src/workbench/memory/noop.py`
- Modify: `src/workbench/models.py`
- Create: `src/workbench/migrations/versions/002_add_choice_index.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test for InteractionEntry.choice_index**

```python
# Append to tests/test_models.py

def test_interaction_entry_has_choice_index():
    from workbench.models import InteractionEntry
    entry = InteractionEntry(
        source_type="github",
        item_summary="Fix auth",
        choice_index=1,
    )
    assert entry.choice_index == 1


def test_interaction_entry_choice_index_default():
    from workbench.models import InteractionEntry
    entry = InteractionEntry(
        source_type="github",
        item_summary="Fix auth",
    )
    assert entry.choice_index is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py -v --tb=short -k "choice_index"`
Expected: TypeError — `choice_index` not a valid field

- [ ] **Step 3: Add choice_index to InteractionEntry**

In `src/workbench/models.py`, add `choice_index` field to `InteractionEntry`:

```python
class InteractionEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_type: str
    item_id: str | None = None
    item_summary: str
    triage_card_full: dict = Field(default_factory=dict)
    enrichment_context: dict = Field(default_factory=dict)
    options_presented: list[dict] = Field(default_factory=list)
    option_chosen: str = ""
    choice_index: int | None = None
    todo_created: dict | None = None
    enrichment_depth: str = "none"
    enrichment_calls: int = 0
    enrichment_time_ms: int = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v --tb=short -k "choice_index"`
Expected: Pass

- [ ] **Step 5: Update MemoryLayer ABC — add entity_type to query_relationships**

In `src/workbench/memory/base.py`:

```python
from abc import ABC, abstractmethod
from workbench.models import TriageCard, TriageResponse, Item, Fact, EntityKnowledge, Relationship


class MemoryLayer(ABC):
    @abstractmethod
    async def record_triage(self, card: TriageCard, response: TriageResponse) -> None: ...
    @abstractmethod
    async def record_entity(self, entity_type: str, entity_id: str, facts: dict) -> None: ...
    @abstractmethod
    async def record_pipeline_decision(self, item: Item, decision: str, reason: str) -> None: ...
    @abstractmethod
    async def query_preferences(self, context: str) -> list[Fact]: ...
    @abstractmethod
    async def query_entity(self, entity_type: str, entity_id: str) -> EntityKnowledge | None: ...
    @abstractmethod
    async def query_relationships(self, entity_type: str, entity_id: str) -> list[Relationship]: ...
    @abstractmethod
    async def is_available(self) -> bool: ...

    async def close(self) -> None:
        pass
```

- [ ] **Step 6: Update NoopMemoryLayer to match new signature**

In `src/workbench/memory/noop.py`:

```python
    async def query_relationships(self, entity_type, entity_id): return []
```

- [ ] **Step 7: Create Alembic migration for choice_index**

```python
# src/workbench/migrations/versions/002_add_choice_index.py
"""Add choice_index to interaction_log.

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interaction_log", sa.Column("choice_index", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("interaction_log", "choice_index")
```

- [ ] **Step 8: Run all workbench tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/workbench/memory/base.py src/workbench/memory/noop.py src/workbench/models.py \
  src/workbench/migrations/versions/002_add_choice_index.py tests/test_models.py
git commit -m "feat: add choice_index to InteractionEntry, update MemoryLayer ABC signature"
```

---

### Task 8: HttpMemoryLayer Wiring

**Files:**
- Modify: `src/workbench/memory/http.py`
- Test: `tests/test_http_memory.py`

- [ ] **Step 1: Write failing tests for new HTTP endpoints**

```python
# Append to tests/test_http_memory.py


@pytest.mark.asyncio
async def test_record_entity_posts_to_memory(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    await layer.record_entity("person", "alice", {"team": "infra"})

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/entity" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["entity_type"] == "person"
    assert payload["entity_id"] == "alice"
    assert payload["facts"]["team"] == "infra"


@pytest.mark.asyncio
async def test_record_entity_does_not_raise_on_failure(layer, mock_http_client):
    mock_http_client.post.side_effect = Exception("Connection refused")
    await layer.record_entity("person", "alice", {"team": "infra"})


@pytest.mark.asyncio
async def test_record_pipeline_decision_posts_to_memory(layer, mock_http_client):
    from workbench.models import Item, ItemCategory, ItemOrigin, Priority

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    item = Item(
        source_type="github", source_id="pr-100",
        summary="PR #100 rate limiting",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P2,
    )
    await layer.record_pipeline_decision(item, "auto_include", "relevance=85")

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/decision" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["item_summary"] == "PR #100 rate limiting"
    assert payload["decision"] == "auto_include"
    assert payload["source_type"] == "github"


@pytest.mark.asyncio
async def test_record_pipeline_decision_does_not_raise_on_failure(layer, mock_http_client):
    from workbench.models import Item, ItemCategory, ItemOrigin, Priority

    mock_http_client.post.side_effect = Exception("Connection refused")
    item = Item(
        source_type="github", source_id="pr-100",
        summary="test", category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P2,
    )
    await layer.record_pipeline_decision(item, "auto_include", "relevance=85")


@pytest.mark.asyncio
async def test_query_entity_returns_entity(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_type": "person",
        "entity_id": "alice",
        "facts": {"team": "infra"},
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    result = await layer.query_entity("person", "alice")

    assert result is not None
    assert result.entity_type == "person"
    assert result.facts["team"] == "infra"


@pytest.mark.asyncio
async def test_query_entity_returns_none_on_404(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock(side_effect=Exception("404"))
    mock_http_client.get.return_value = mock_response

    result = await layer.query_entity("person", "unknown")
    assert result is None


@pytest.mark.asyncio
async def test_query_entity_returns_none_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")
    result = await layer.query_entity("person", "alice")
    assert result is None


@pytest.mark.asyncio
async def test_query_relationships_returns_list(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "relationships": [
            {"from_entity": "alice", "to_entity": "infra-core", "relation": "reviews"}
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    rels = await layer.query_relationships("person", "alice")

    assert len(rels) == 1
    assert rels[0].from_entity == "alice"
    assert rels[0].relation == "reviews"


@pytest.mark.asyncio
async def test_query_relationships_returns_empty_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")
    rels = await layer.query_relationships("person", "alice")
    assert rels == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_http_memory.py -v --tb=short -k "record_entity or record_pipeline or query_entity or query_relationships"`
Expected: AssertionError — methods are no-ops returning None/[]

- [ ] **Step 3: Implement the HTTP calls in HttpMemoryLayer**

Replace the stub methods in `src/workbench/memory/http.py`:

```python
    async def record_entity(self, entity_type: str, entity_id: str, facts: dict) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/entity",
                json={
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "facts": facts,
                },
            )
        except Exception as e:
            logger.warning("Memory service record_entity failed: %s", e)

    async def record_pipeline_decision(self, item: Item, decision: str, reason: str) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/decision",
                json={
                    "item_summary": item.summary,
                    "decision": decision,
                    "reason": reason,
                    "source_type": item.source_type,
                },
            )
        except Exception as e:
            logger.warning("Memory service record_pipeline_decision failed: %s", e)

    async def query_entity(self, entity_type: str, entity_id: str) -> EntityKnowledge | None:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/entity",
                params={"entity_type": entity_type, "entity_id": entity_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return EntityKnowledge(
                entity_type=data["entity_type"],
                entity_id=data["entity_id"],
                facts=data["facts"],
            )
        except Exception as e:
            logger.warning("Memory service query_entity failed: %s", e)
            return None

    async def query_relationships(self, entity_type: str, entity_id: str) -> list[Relationship]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/relationships",
                params={"entity_type": entity_type, "entity_id": entity_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                Relationship(
                    from_entity=r["from_entity"],
                    to_entity=r["to_entity"],
                    relation=r["relation"],
                )
                for r in data.get("relationships", [])
            ]
        except Exception as e:
            logger.warning("Memory service query_relationships failed: %s", e)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_http_memory.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/workbench/memory/http.py tests/test_http_memory.py
git commit -m "feat: wire HttpMemoryLayer entity/decision/relationship HTTP calls"
```

---

### Task 9: Enricher ABC and GitHub Enricher Memory Integration

**Files:**
- Modify: `src/workbench/providers/enrichment/base.py`
- Modify: `src/workbench/providers/enrichment/stub.py`
- Modify: `src/workbench/providers/enrichment/github.py`
- Modify: `src/workbench/pipeline/enrichment.py`
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_github_enricher.py`

- [ ] **Step 1: Write failing test for enricher with memory parameter**

```python
# Append to tests/test_github_enricher.py

@pytest.mark.asyncio
async def test_enrich_accepts_memory_parameter():
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.memory.noop import NoopMemoryLayer
    from workbench.models import ExtractedItem, RawItem, ItemCategory, EnrichmentBudget

    enricher = StubEnricher()
    memory = NoopMemoryLayer()
    item = ExtractedItem(
        summary="test",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(id="1", source_type="manual", source_label="test", raw_text="test"),
    )
    result = await enricher.enrich(item, "shallow", EnrichmentBudget(), memory=memory)
    assert result["calls_made"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_github_enricher.py -v --tb=short -k "memory_parameter"`
Expected: TypeError — unexpected keyword argument 'memory'

- [ ] **Step 3: Update ContextEnricher ABC**

In `src/workbench/providers/enrichment/base.py`:

```python
from abc import ABC, abstractmethod
from workbench.memory.base import MemoryLayer
from workbench.models import ExtractedItem, EnrichmentBudget


class ContextEnricher(ABC):
    @abstractmethod
    async def enrich(
        self, item: ExtractedItem, depth: str, budget: EnrichmentBudget,
        *, memory: MemoryLayer | None = None,
    ) -> dict: ...

    async def close(self) -> None:
        pass
```

- [ ] **Step 4: Update StubEnricher**

In `src/workbench/providers/enrichment/stub.py`:

```python
    async def enrich(self, item, depth, budget, *, memory=None):
        return {"calls_made": 0, "time_ms": 0, "context": {}}
```

- [ ] **Step 5: Update GitHubEnricher signature and add memory integration**

In `src/workbench/providers/enrichment/github.py`, update the `enrich` method signature and add memory queries/recording:

```python
    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget, *, memory=None) -> dict:
        if item.raw_item.source_type != "github":
            return {"calls_made": 0, "time_ms": 0, "context": {}}

        start = time.monotonic()
        context = {}
        calls_made = 0

        try:
            raw_data = json.loads(item.raw_item.raw_text)
        except (json.JSONDecodeError, TypeError):
            raw_data = {}

        author = raw_data.get("author", {})
        author_login = None
        if isinstance(author, dict):
            author_login = author.get("login", "unknown")
            context["author"] = author_login
        elif isinstance(author, str):
            author_login = author
            context["author"] = author

        if memory and author_login:
            entity = await memory.query_entity("person", author_login)
            if entity:
                if entity.facts.get("team"):
                    context["author_team"] = entity.facts["team"]
                if entity.facts.get("role"):
                    context["author_role"] = entity.facts["role"]

        source_id = item.raw_item.id
        url = raw_data.get("url", "")
        is_pr = "/pull/" in url or "gh-pr-" in source_id

        repo, number = self._parse_url(url)
        if not repo or not number:
            repo, number = self._parse_source_id(source_id)

        if repo and number:
            try:
                if is_pr:
                    details = await self._gh_json(
                        "pr", "view", str(number), "--repo", repo,
                        "--json", "files,reviewDecision,labels,statusCheckRollup",
                    )
                    calls_made = 1
                    files = details.get("files", [])
                    context["files_changed"] = len(files)
                    review = details.get("reviewDecision", "")
                    if review:
                        context["review_status"] = review.lower()
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    checks = details.get("statusCheckRollup", [])
                    if checks:
                        conclusions = [c.get("conclusion", "") for c in checks]
                        if all(c == "SUCCESS" for c in conclusions):
                            context["ci"] = "passing"
                        elif any(c == "FAILURE" for c in conclusions):
                            context["ci"] = "failing"
                        else:
                            context["ci"] = "pending"
                else:
                    details = await self._gh_json(
                        "issue", "view", str(number), "--repo", repo,
                        "--json", "labels,assignees,comments",
                    )
                    calls_made = 1
                    labels = details.get("labels", [])
                    if labels:
                        context["labels"] = ", ".join(l.get("name", "") for l in labels)
                    assignees = details.get("assignees", [])
                    if assignees:
                        context["assignees"] = ", ".join(a.get("login", "") for a in assignees)
                    comments = details.get("comments", [])
                    context["comment_count"] = len(comments)
            except Exception as e:
                logger.warning("GitHub enrichment failed for %s: %s", source_id, e)

        if memory:
            if author_login:
                author_facts = {"source": "github"}
                if context.get("labels"):
                    author_facts["recent_labels"] = context["labels"]
                await memory.record_entity("person", author_login, author_facts)
            if repo:
                repo_facts = {"source": "github"}
                if context.get("ci"):
                    repo_facts["ci_status"] = context["ci"]
                await memory.record_entity("repo", repo, repo_facts)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"calls_made": calls_made, "time_ms": elapsed_ms, "context": context}
```

- [ ] **Step 6: Update enrichment pipeline to pass memory**

In `src/workbench/pipeline/enrichment.py`:

```python
from workbench.memory.base import MemoryLayer
from workbench.providers.enrichment.base import ContextEnricher
from workbench.models import ExtractedItem, EnrichmentBudget


async def enrich_item(
    enricher: ContextEnricher, item: ExtractedItem,
    depth: str = "shallow", budget: EnrichmentBudget | None = None,
    memory: MemoryLayer | None = None,
) -> dict:
    if budget is None:
        budget = EnrichmentBudget()
    return await enricher.enrich(item, depth, budget, memory=memory)
```

- [ ] **Step 7: Update PipelineEngine to pass memory to enrich_item**

In `src/workbench/pipeline/engine.py`, update the `enrich_item` call inside `_process_extracted_item()`:

```python
            enrichment = await enrich_item(self.enricher, ext_item, memory=self.memory)
```

- [ ] **Step 8: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add src/workbench/providers/enrichment/base.py src/workbench/providers/enrichment/stub.py \
  src/workbench/providers/enrichment/github.py src/workbench/pipeline/enrichment.py \
  src/workbench/pipeline/engine.py tests/test_github_enricher.py
git commit -m "feat: add memory parameter to enricher ABC, wire GitHub enricher entity queries"
```

---

### Task 10: Noise Filter Entity and Relationship Integration

**Files:**
- Modify: `src/workbench/pipeline/filter.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing test for filter with entity/relationship context**

```python
# Append to tests/test_pipeline.py

@pytest.mark.asyncio
async def test_score_and_decide_queries_entity_and_relationships():
    from workbench.pipeline.filter import score_and_decide
    from workbench.memory.base import MemoryLayer
    from workbench.models import (
        ExtractedItem, ItemCategory, RawItem, Fact,
        EntityKnowledge, Relationship,
    )
    from unittest.mock import AsyncMock

    mock_memory = AsyncMock(spec=MemoryLayer)
    mock_memory.query_preferences.return_value = [
        Fact(content="User prefers auth diffs"),
    ]
    mock_memory.query_entity.return_value = EntityKnowledge(
        entity_type="person", entity_id="alice", facts={"team": "infra"},
    )
    mock_memory.query_relationships.return_value = [
        Relationship(from_entity="alice", to_entity="infra-core", relation="reviews"),
    ]

    mock_llm = AsyncMock()
    mock_llm.score_relevance.return_value = (85, 90)

    mock_rules = AsyncMock()
    mock_rules.get_rules.return_value = []
    mock_rules.get_source_rules.return_value = []

    item = ExtractedItem(
        summary="alice opened PR",
        category=ItemCategory.ACTION_ITEM,
        source_context="ctx",
        raw_item=RawItem(id="gh-pr-1", source_type="github", source_label="PR #1", raw_text="test"),
    )

    action, relevance, confidence = await score_and_decide(
        mock_llm, mock_memory, mock_rules, item,
    )

    mock_memory.query_entity.assert_called_once()
    mock_memory.query_relationships.assert_called_once()

    call_args = mock_llm.score_relevance.call_args
    preference_facts = call_args.args[1]
    assert len(preference_facts) == 3
    assert any("infra" in f.content for f in preference_facts)
    assert any("reviews" in f.content for f in preference_facts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v --tb=short -k "queries_entity"`
Expected: AssertionError — memory.query_entity not called

- [ ] **Step 3: Update score_and_decide to query entity and relationships**

Replace `src/workbench/pipeline/filter.py`:

```python
import asyncio

from workbench.providers.llm.base import LLMProvider
from workbench.memory.base import MemoryLayer
from workbench.storage.base import FilterRuleStore
from workbench.models import ExtractedItem, Fact


async def score_and_decide(
    llm: LLMProvider,
    memory: MemoryLayer,
    filter_rules: FilterRuleStore,
    item: ExtractedItem,
    include_threshold: int = 70,
    drop_threshold: int = 30,
    confidence_threshold: int = 70,
) -> tuple[str, int, int]:
    """Returns (action, relevance, confidence). Action is 'auto_include', 'auto_drop', or 'triage'."""
    pref_task = memory.query_preferences(item.summary)
    entity_task = memory.query_entity(item.raw_item.source_type, item.raw_item.id)
    rel_task = memory.query_relationships(item.raw_item.source_type, item.raw_item.id)

    preference_facts, entity, relationships = await asyncio.gather(
        pref_task, entity_task, rel_task,
    )

    if entity:
        facts_str = ", ".join(f"{k}: {v}" for k, v in entity.facts.items())
        preference_facts.append(
            Fact(content=f"{entity.entity_type} {entity.entity_id}: {facts_str}", source="entity")
        )

    for rel in relationships:
        preference_facts.append(
            Fact(
                content=f"{rel.from_entity} {rel.relation} {rel.to_entity}",
                source="relationship",
            )
        )

    rules = await filter_rules.get_rules()
    source_rules = await filter_rules.get_source_rules(item.raw_item.source_type)
    all_rules = rules + [r for r in source_rules if r not in rules]

    relevance, confidence = await llm.score_relevance(item, preference_facts, all_rules)

    if relevance >= include_threshold and confidence >= confidence_threshold:
        return "auto_include", relevance, confidence
    elif relevance < drop_threshold and confidence >= confidence_threshold:
        return "auto_drop", relevance, confidence
    else:
        return "triage", relevance, confidence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/workbench/pipeline/filter.py tests/test_pipeline.py
git commit -m "feat: wire entity/relationship queries into noise filter scoring"
```

---

### Task 11: Triage API — Full Card Dict and Choice Index

**Files:**
- Modify: `src/workbench/api/triage.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test for full card dict and choice_index in interaction log**

```python
# Append to tests/test_api.py (or add as a new test in the existing test_api module)

@pytest.mark.asyncio
async def test_triage_respond_stores_full_card_and_choice_index(stores):
    from workbench.models import TriageCard, TriageOption, TriageResponse, InteractionEntry

    card = TriageCard(
        card_content={"summary": "Fix auth", "source_type": "github"},
        options=[
            TriageOption(label="Add todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
        relevance_score=45,
        confidence_score=60,
    )
    await stores.triage.save_card(card)

    from fastapi.testclient import TestClient
    from workbench.main import create_app
    app = create_app()
    app.state.stores = stores
    from workbench.memory.noop import NoopMemoryLayer
    app.state.memory = NoopMemoryLayer()

    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/triage/respond",
            json={"card_id": card.id, "choice": 1},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200

    entries = await stores.interactions.get_all()
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.choice_index == 1
    assert "id" in entry.triage_card_full
    assert "options" in entry.triage_card_full
    assert "relevance_score" in entry.triage_card_full
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -v --tb=short -k "full_card_and_choice"`
Expected: AssertionError — choice_index is None, triage_card_full doesn't have card-level fields

- [ ] **Step 3: Update triage endpoint to store full card and choice_index**

In `src/workbench/api/triage.py`, update the `InteractionEntry` construction:

```python
    entry = InteractionEntry(
        source_type=card.card_content.get("source_type", "unknown"),
        item_summary=card.card_content.get("summary", ""),
        triage_card_full=card.model_dump(),
        options_presented=[o.model_dump() for o in card.options],
        option_chosen=option.label,
        choice_index=response.choice,
    )
```

The key changes:
1. `triage_card_full=card.model_dump()` instead of `card.card_content` — stores the full card including `id`, `options`, `relevance_score`, `confidence_score`
2. `choice_index=response.choice` — stores the 1-based numeric choice

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/workbench/api/triage.py tests/test_api.py
git commit -m "feat: store full card dict and choice_index in interaction log"
```

---

### Task 12: Memory Rebuild Script

**Files:**
- Create: `src/memory/scripts/__init__.py`
- Create: `src/memory/scripts/rebuild.py`
- Create: `src/memory/tests/test_rebuild.py`

- [ ] **Step 1: Create scripts package**

```bash
mkdir -p src/memory/scripts
touch src/memory/scripts/__init__.py
```

- [ ] **Step 2: Write failing tests for rebuild logic**

```python
# src/memory/tests/test_rebuild.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_replay_interactions_posts_to_memory():
    from memory.scripts.rebuild import replay_interactions

    interactions = [
        {
            "id": "i1",
            "timestamp": "2026-06-01T12:00:00Z",
            "triage_card_full": {
                "id": "c1",
                "card_content": {"summary": "Fix auth", "source_type": "github"},
                "options": [{"label": "Add todo", "action": "add_todo"}],
                "relevance_score": 45,
            },
            "choice_index": 1,
        },
    ]

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    stats = await replay_interactions(mock_client, interactions, "http://localhost:8422")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "/record/triage" in call_args[0][0]
    assert stats["replayed"] == 1
    assert stats["skipped"] == 0


@pytest.mark.asyncio
async def test_replay_skips_entries_without_choice_index():
    from memory.scripts.rebuild import replay_interactions

    interactions = [
        {
            "id": "i1",
            "timestamp": "2026-06-01T12:00:00Z",
            "triage_card_full": {"summary": "old card"},
            "choice_index": None,
        },
    ]

    mock_client = AsyncMock()
    stats = await replay_interactions(mock_client, interactions, "http://localhost:8422")

    mock_client.post.assert_not_called()
    assert stats["replayed"] == 0
    assert stats["skipped"] == 1


@pytest.mark.asyncio
async def test_replay_constructs_triage_record_from_full_card():
    from memory.scripts.rebuild import replay_interactions

    interactions = [
        {
            "id": "i2",
            "timestamp": "2026-06-01T12:00:00Z",
            "triage_card_full": {
                "id": "c2",
                "card_content": {"summary": "Review PR", "source_type": "github"},
                "options": [
                    {"label": "Add todo", "action": "add_todo", "details": {}},
                    {"label": "Skip", "action": "skip", "details": {}},
                ],
                "relevance_score": 60,
            },
            "choice_index": 2,
        },
    ]

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    await replay_interactions(mock_client, interactions, "http://localhost:8422")

    payload = mock_client.post.call_args[1]["json"]
    assert payload["card"]["id"] == "c2"
    assert payload["response"]["choice"] == 2


@pytest.mark.asyncio
async def test_reset_graph_called_when_flag_set():
    from memory.scripts.rebuild import reset_memory_graph

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    await reset_memory_graph(mock_client, "http://localhost:8422")

    call_args = mock_client.post.call_args
    assert "/admin/reset-graph" in call_args[0][0]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd src/memory && python -m pytest tests/test_rebuild.py -v --tb=short`
Expected: ImportError — module doesn't exist

- [ ] **Step 4: Implement rebuild script**

```python
# src/memory/scripts/rebuild.py
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import asyncpg
import httpx

logger = logging.getLogger(__name__)


async def reset_memory_graph(client: httpx.AsyncClient, memory_url: str) -> None:
    resp = await client.post(f"{memory_url}/admin/reset-graph")
    resp.raise_for_status()
    logger.info("Graph reset complete")


async def fetch_interactions(dsn: str) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, timestamp, triage_card_full, choice_index "
            "FROM interaction_log ORDER BY timestamp"
        )
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                "triage_card_full": r["triage_card_full"],
                "choice_index": r["choice_index"],
            }
            for r in rows
        ]
    finally:
        await conn.close()


async def get_queue_depth(client: httpx.AsyncClient, memory_url: str) -> int:
    resp = await client.get(f"{memory_url}/admin/queue-depth")
    resp.raise_for_status()
    return resp.json()["depth"]


async def replay_interactions(
    client: httpx.AsyncClient, interactions: list[dict], memory_url: str,
    batch_size: int = 10, max_queue_depth: int = 20,
) -> dict:
    stats = {"replayed": 0, "skipped": 0, "failed": 0}

    for interaction in interactions:
        card_full = interaction.get("triage_card_full", {})
        choice_index = interaction.get("choice_index")

        if not choice_index or not card_full.get("id"):
            logger.warning(
                "Skipping interaction %s: missing choice_index or incomplete card",
                interaction["id"],
            )
            stats["skipped"] += 1
            continue

        payload = {
            "card": card_full,
            "response": {"card_id": card_full["id"], "choice": choice_index},
        }

        try:
            resp = await client.post(f"{memory_url}/record/triage", json=payload)
            resp.raise_for_status()
            stats["replayed"] += 1
        except Exception as e:
            logger.error("Failed to replay interaction %s: %s", interaction["id"], e)
            stats["failed"] += 1

        if stats["replayed"] % batch_size == 0 and stats["replayed"] > 0:
            depth = await get_queue_depth(client, memory_url)
            while depth > max_queue_depth:
                logger.info("Queue depth %d, waiting...", depth)
                await asyncio.sleep(2)
                depth = await get_queue_depth(client, memory_url)
            total = stats["replayed"] + stats["skipped"] + stats["failed"]
            logger.info(
                "Replayed %d/%d interactions, queue depth: %d",
                stats["replayed"], len(interactions), depth,
            )

    return stats


async def main(
    workbench_dsn: str, memory_url: str, reset: bool = False,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    async with httpx.AsyncClient(timeout=30) as client:
        if reset:
            logger.info("Resetting graph...")
            await reset_memory_graph(client, memory_url)

        logger.info("Fetching interactions from workbench PG...")
        interactions = await fetch_interactions(workbench_dsn)
        logger.info("Found %d interactions", len(interactions))

        if not interactions:
            logger.info("Nothing to replay")
            return

        stats = await replay_interactions(client, interactions, memory_url)
        logger.info(
            "Done: replayed=%d, skipped=%d, failed=%d",
            stats["replayed"], stats["skipped"], stats["failed"],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild memory graph from interaction log")
    parser.add_argument(
        "--workbench-dsn",
        default="postgres://workbench:workbench@localhost:5432/workbench",
    )
    parser.add_argument(
        "--memory-url",
        default="http://localhost:8422",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe graph before replaying",
    )

    args = parser.parse_args()
    asyncio.run(main(args.workbench_dsn, args.memory_url, args.reset))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/memory && python -m pytest tests/test_rebuild.py -v --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/memory/scripts/ src/memory/tests/test_rebuild.py
git commit -m "feat(memory): add rebuild script to replay interaction log"
```

---

### Task 13: Workbench Storage — InteractionEntry choice_index Persistence

**Files:**
- Modify: `src/workbench/storage/postgres/interactions.py:15-37` (append method)
- Modify: `src/workbench/storage/postgres/interactions.py:58-89` (_row_to_entry method)

The Alembic migration was created in Task 7. This task ensures the PostgreSQL store reads/writes the `choice_index` column.

- [ ] **Step 1: Update the `append` method to include choice_index**

In `src/workbench/storage/postgres/interactions.py`, update the INSERT in `append()`:

```python
    async def append(self, entry: InteractionEntry) -> None:
        await self.pool.execute(
            """INSERT INTO interaction_log
               (id, timestamp, source_type, item_id, item_summary,
                triage_card_full, enrichment_context, options_presented,
                option_chosen, choice_index, todo_created, enrichment_depth,
                enrichment_calls, enrichment_time_ms)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
                       $9, $10, $11::jsonb, $12, $13, $14)""",
            entry.id,
            entry.timestamp,
            entry.source_type,
            entry.item_id,
            entry.item_summary,
            json.dumps(entry.triage_card_full),
            json.dumps(entry.enrichment_context),
            json.dumps(entry.options_presented),
            entry.option_chosen,
            entry.choice_index,
            json.dumps(entry.todo_created) if entry.todo_created else None,
            entry.enrichment_depth,
            entry.enrichment_calls,
            entry.enrichment_time_ms,
        )
```

- [ ] **Step 2: Update `_row_to_entry` to read choice_index**

In the same file, add `choice_index` to the `InteractionEntry` construction in `_row_to_entry()`:

```python
        return InteractionEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            source_type=row["source_type"],
            item_id=row["item_id"],
            item_summary=row["item_summary"],
            triage_card_full=triage_card_full,
            enrichment_context=enrichment_context,
            options_presented=options_presented,
            option_chosen=row["option_chosen"],
            choice_index=row.get("choice_index"),
            todo_created=todo,
            enrichment_depth=row["enrichment_depth"],
            enrichment_calls=row["enrichment_calls"],
            enrichment_time_ms=row["enrichment_time_ms"],
        )
```

- [ ] **Step 3: Run the Alembic migration**

Run: `make migrate`
Expected: Migration 002 applies successfully

- [ ] **Step 4: Run integration tests**

Run: `python -m pytest tests/test_api.py -v --tb=short`
Expected: All pass, including the full-card test from Task 11

- [ ] **Step 5: Commit**

```bash
git add src/workbench/storage/postgres/interactions.py
git commit -m "feat: persist choice_index in interaction_log storage"
```

---

### Task 14: Full Integration Verification

No new code — this task verifies everything works together.

- [ ] **Step 1: Run all memory service tests**

Run: `cd src/memory && python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 2: Run all workbench tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 3: Start services and run a smoke test**

Run: `make up && sleep 5 && make health`

Verify:
- Memory service health shows `neo4j: connected`, `postgres: connected`
- Workbench health shows all components healthy

- [ ] **Step 4: Test entity recording via curl**

```bash
curl -s -X POST http://localhost:8422/record/entity \
  -H "Content-Type: application/json" \
  -d '{"entity_type":"person","entity_id":"test-user","facts":{"team":"test"}}' | python3 -m json.tool
```

Expected: `{"status": "recorded"}`

- [ ] **Step 5: Test entity querying via curl**

```bash
curl -s "http://localhost:8422/query/entity?entity_type=person&entity_id=test-user" | python3 -m json.tool
```

Expected: `{"entity_type": "person", "entity_id": "test-user", "facts": {"team": "test"}}`

- [ ] **Step 6: Test decision recording via curl**

```bash
curl -s -X POST http://localhost:8422/record/decision \
  -H "Content-Type: application/json" \
  -d '{"item_summary":"PR #100","decision":"auto_include","reason":"relevance=85","source_type":"github"}' | python3 -m json.tool
```

Expected: `{"status": "queued", "entry_id": "..."}`

- [ ] **Step 7: Test queue depth via curl**

```bash
curl -s "http://localhost:8422/admin/queue-depth" | python3 -m json.tool
```

Expected: `{"depth": N, "dead_letters": 0}`

- [ ] **Step 8: Test relationship querying via curl**

```bash
curl -s "http://localhost:8422/query/relationships?entity_type=person&entity_id=test-user" | python3 -m json.tool
```

Expected: `{"relationships": [...]}` (may be empty if no relationships have been inferred yet)

- [ ] **Step 9: Commit any fixes**

If any smoke test failures revealed issues, fix and commit them.

```bash
git add -A && git commit -m "fix: integration fixes from Phase 1c smoke test"
```
