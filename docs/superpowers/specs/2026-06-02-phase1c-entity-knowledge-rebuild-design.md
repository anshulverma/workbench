# Phase 1c: Entity Knowledge, Decision Recording, and Memory Rebuild — Design Spec

## Context

Phase 1b delivered the memory service with triage interaction recording (structured writes + LLM episode extraction) and preference querying. Four API endpoints return 501 stubs: `record/entity`, `record/decision`, `query/entity`, `query/relationships`. The MemoryLayer ABC already defines methods for all four. Phase 1c fills in these stubs, wires callers in the pipeline, and adds a rebuild mechanism.

## Goals

1. **Entity knowledge** — Record facts about people, repos, teams. Query them to enrich triage context and inform noise filter scoring.
2. **Pipeline decision recording** — Record why the pipeline included/dropped items. Full LLM episode extraction to learn patterns.
3. **Relationship querying** — Query the graph for relationships between entities (emergent from episode extraction).
4. **Memory rebuild** — CLI script to replay the interaction log from workbench PG into the memory service.
5. **Pipeline integration** — Wire entity/relationship queries into both the noise filter and enricher.

## Architecture

No new services or databases. Phase 1c extends the existing memory service. The key architectural decision is **dual storage for entities**: PostgreSQL for fast key-value lookups, Neo4j graph for relationship traversal.

```
Workbench Pipeline
  ├─ Enrichment stage ─── POST /record/entity (sync, PG + graph dual-write)
  │                       GET /query/entity (reads PG only — fast)
  ├─ Engine ──────────── POST /record/decision (queued, async)
  ├─ Noise filter ────── GET /query/preferences (existing)
  │                      GET /query/entity (flatten to Fact for LLM scoring)
  │                      GET /query/relationships (custom Cypher, flatten to Fact)
  └─ Triage ──────────── POST /record/triage (existing)

Rebuild script ──── reads workbench PG interaction_log
                    POSTs to /record/triage (replays through queue)
```

## Entity Knowledge

### Storage: PG + Graph Dual-Write

Entities use two storage backends optimized for different access patterns:

**PostgreSQL `entities` table** (in memory database) — fast key-value CRUD:
```sql
CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    facts JSONB NOT NULL DEFAULT '{}',
    graph_uuid TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_type, entity_id)
)
```

- `graph_uuid` stores the Neo4j node UUID returned by `add_triplet`, enabling fast relationship lookups via `EntityEdge.get_by_node_uuid()`
- `facts` uses JSONB merge on upsert: `UPDATE SET facts = entities.facts || $new_facts` — keys in the new facts win, existing keys are preserved

**Neo4j graph** — relationship traversal:
- `add_triplet()` creates entity nodes connected to fact nodes
- Relationships emerge from triage/decision episode extraction
- Queried via custom Cypher for `query_relationships`

### Write: `POST /record/entity`

Request:
```json
{
  "entity_type": "person",
  "entity_id": "alice",
  "facts": {"team": "infra", "role": "tech lead", "repos": ["infra-core"]}
}
```

Response: `200 OK` with `{"status": "recorded"}`

Implementation (synchronous, no queue):
1. UPSERT into PG `entities` table (merge facts via `||`)
2. Create/update graph nodes via `add_triplet()`:
   - Source node: `(entity_type:entity_id)` e.g., `(person:alice)`
   - For each fact key-value: `(person:alice) --[has_fact {key}]--> (value)`
3. Store the resolved node UUID from `add_triplet` result back into PG `graph_uuid`

Repeated calls merge facts — `record_entity("person", "alice", {repos: ["new-repo"]})` adds `repos` without losing `team`.

### Read: `GET /query/entity`

Request: `?entity_type=person&entity_id=alice`

Response: `200 OK` with `{"entity_type": "person", "entity_id": "alice", "facts": {...}}` or `404`.

Implementation: reads from PG `entities` table — indexed lookup by `(entity_type, entity_id)`. Does NOT touch Neo4j. Sub-millisecond latency.

### Where workbench calls it

**Enrichment stage** — The `ContextEnricher.enrich()` signature changes to accept `MemoryLayer`. The enricher:
1. Checks memory first via `query_entity()` before making external API calls (e.g., if we already know alice's team, skip the `gh` CLI call)
2. Records new entity knowledge via `record_entity()` as a side effect of enrichment

This requires changing the `ContextEnricher` ABC: `async def enrich(self, item, depth, budget, memory)`. `StubEnricher` ignores the memory parameter. `GitHubEnricher` uses it. The pipeline engine passes `self.memory` when calling `enrich_item()`.

**Noise filter** — `score_and_decide()` queries `query_entity()` for entities mentioned in the item, flattens results to `Fact(content="alice is tech lead on infra team", source="entity")`, and appends them to the preference_facts list passed to `llm.score_relevance()`. No change to the LLM provider interface.

## Pipeline Decision Recording

### Write: `POST /record/decision`

Request:
```json
{
  "item_summary": "PR #100 rate limiting",
  "decision": "auto_include",
  "reason": "relevance=85",
  "source_type": "github"
}
```

Response: `202 Accepted` with `{"status": "queued", "entry_id": "..."}`

Implementation: Two-layer write, same pattern as triage:

**Layer 1 (deterministic):** Structured edge via `add_triplet()`:
- `(pipeline) --[included {reason, source_type}]--> (pattern: item_summary)` for includes
- `(pipeline) --[dropped {reason, source_type}]--> (pattern: item_summary)` for drops

**Layer 2 (LLM):** Episode ingestion via `add_episode()` with a decision-specific extraction prompt:
```
You are extracting patterns about pipeline filtering decisions.
Focus on:
- What types of items the pipeline consistently includes or drops
- Source types, topics, or patterns that predict inclusion/exclusion
- Threshold behaviors (items near the relevance cutoff)

Extract facts in the form: "Pipeline [always/never/usually] [includes/drops] [item pattern] [when condition]"
```

### Queue changes

The `pending_ingestions` table `CREATE TABLE IF NOT EXISTS` adds a `type TEXT NOT NULL DEFAULT 'triage'` column. The worker dispatches to the appropriate handler based on type. No ALTER TABLE — users with existing data wipe the memory PG data dir (the memory database is derived and rebuildable via the rebuild script, and entities survive in the PG entities table).

### HttpMemoryLayer wiring

The MemoryLayer ABC signature is `record_pipeline_decision(item: Item, decision, reason)`. HttpMemoryLayer extracts flat fields from the Item:
```python
async def record_pipeline_decision(self, item, decision, reason):
    await self._client.post("/record/decision", json={
        "item_summary": item.summary,
        "decision": decision,
        "reason": reason,
        "source_type": item.source_type,
    })
```

The ABC signature stays unchanged. The memory service API takes flat fields. The memory service never knows about the Item model.

## Relationship Querying

### Read: `GET /query/relationships`

Request: `?entity_id=alice`

Response: `200 OK` with:
```json
{
  "relationships": [
    {"from_entity": "alice", "to_entity": "infra-core", "relation": "reviews"},
    {"from_entity": "alice", "to_entity": "bob", "relation": "collaborates_with"}
  ]
}
```

Implementation: Custom Cypher query via `graphiti.driver.execute_query()`:
```cypher
MATCH (n:Entity {uuid: $uuid})-[e:RELATES_TO]-(m:Entity)
RETURN n.name AS from_entity, m.name AS to_entity, e.name AS relation, e.fact AS fact
```

The entity's `graph_uuid` (stored in the PG entities table) is used to look up the Neo4j node. If the entity has no `graph_uuid` in PG, returns empty list.

### How relationships emerge

No explicit "create relationship" endpoint. Relationships are inferred by Graphiti's LLM extraction from:
1. **Triage episodes** — "user always prioritizes alice's PRs" → relationship between user and alice
2. **Entity facts** — recording that alice works on infra-core creates an implicit relationship
3. **Decision episodes** — "pipeline always includes items from infra-core" → relationship between pipeline and repo

### Where workbench calls it

**Noise filter** — `score_and_decide()` queries `query_relationships()` for entities mentioned in the item, flattens results to `Fact(content="alice reviews infra-core repo", source="relationship")`, and appends to the preference_facts list. Same flattening approach as entity knowledge — no LLM provider interface change.

## Memory Rebuild

### CLI script: `src/memory/scripts/rebuild.py`

Reconstructs the knowledge graph from the interaction log in workbench's PostgreSQL.

**Usage:**
```bash
python -m memory.scripts.rebuild \
  --workbench-dsn postgres://workbench:workbench@localhost:5432/workbench \
  --memory-url http://localhost:8422 \
  --reset  # optional: wipe graph first
```

**How it works:**
1. Connects to workbench PG, reads `interaction_log` table ordered by timestamp
2. If `--reset`: calls `POST /admin/reset-graph` on the memory service to wipe Neo4j
3. For each interaction entry:
   - Constructs a `TriageRecordRequest` from `triage_card_full` (full card dict) + `choice_index` (integer)
   - POSTs to `/record/triage`
4. Polls `GET /admin/queue-depth` between batches to avoid overwhelming the queue
5. Reports progress to stdout: `Replayed 150/500 interactions, queue depth: 3`

**Rebuild scope: triage-only.** Entity knowledge survives in the memory service's PG entities table (not affected by Neo4j wipe). Pipeline decision patterns re-learn organically from new pipeline runs. Triage preferences are the primary learning signal — high-signal, low-volume.

### InteractionEntry changes for rebuild support

1. **`triage_card_full` stores the full card dict** — Change to `card.model_dump()` (includes id, options, relevance_score) instead of just `card.card_content`.
2. **Add `choice_index: int` field** — Numeric choice (1-based). Requires Alembic migration.

### Admin endpoints

**`POST /admin/reset-graph`** — Wipes all nodes and edges from Neo4j. Only when `MEMORY_ADMIN_ENABLED=true`. Returns `403` when disabled.

**`GET /admin/queue-depth`** — Returns `{"depth": N, "dead_letters": M}`. Always available.

## API Summary

### New endpoints (replacing 501 stubs)

| Method | Path | Sync/Async | Description |
|--------|------|-----------|-------------|
| POST | `/record/entity` | Sync (200) | PG upsert + graph add_triplet |
| POST | `/record/decision` | Async (202) | Queue for episode ingestion |
| GET | `/query/entity` | Sync (200) | PG indexed lookup |
| GET | `/query/relationships` | Sync (200) | Custom Cypher via graph_uuid |

### New admin endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/reset-graph` | Wipe Neo4j (requires MEMORY_ADMIN_ENABLED) |
| GET | `/admin/queue-depth` | Queue depth + dead letter count |

## Request/Response Models

### New models in `memory/models.py`

```python
class EntityRecordRequest(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict

class DecisionRecordRequest(BaseModel):
    item_summary: str
    decision: str  # "auto_include" or "auto_drop"
    reason: str
    source_type: str = "unknown"

class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict

class RelationshipsResponse(BaseModel):
    relationships: list[dict]  # [{from_entity, to_entity, relation}]

class QueueDepthResponse(BaseModel):
    depth: int
    dead_letters: int
```

## File Changes

### Memory service (`src/memory/`)

| File | Change |
|------|--------|
| `memory/models.py` | Add EntityRecordRequest, DecisionRecordRequest, EntityResponse, RelationshipsResponse, QueueDepthResponse |
| `memory/graphiti_layer.py` | Add record_entity(), record_decision(), query_entity(), query_relationships() |
| `memory/extraction.py` | Add DECISION_EXTRACTION_PROMPT, format_decision_narrative() |
| `memory/queue.py` | Add `type` column to CREATE TABLE, add `entities` table creation in initialize() |
| `memory/main.py` | Replace 4 stubs with real endpoints, add 2 admin endpoints, dispatch worker by type |
| `scripts/rebuild.py` | New CLI rebuild script |
| `tests/test_graphiti_layer.py` | Add tests for entity/decision/query methods |
| `tests/test_extraction.py` | Add tests for decision narrative formatting |
| `tests/test_queue.py` | Add tests for entity CRUD in PG |
| `tests/test_rebuild.py` | Test rebuild script logic (mocked HTTP) |

### Workbench (`src/workbench/`)

| File | Change |
|------|--------|
| `memory/http.py` | Wire record_entity, record_pipeline_decision, query_entity, query_relationships to HTTP |
| `providers/enrichment/base.py` | Add `memory: MemoryLayer` parameter to `enrich()` |
| `providers/enrichment/stub.py` | Accept and ignore memory parameter |
| `providers/enrichment/github.py` | Check memory before external calls, record entities after |
| `pipeline/enrichment.py` | Pass memory to enricher |
| `pipeline/engine.py` | Pass memory to enrich_item() |
| `pipeline/filter.py` | Query entity/relationships, flatten to Fact, append to scoring context |
| `models.py` | Add `choice_index: int` to InteractionEntry |
| `api/triage.py` | Store `card.model_dump()` in triage_card_full, store choice_index |
| `migrations/` | Alembic migration: add choice_index column to interaction_log |
| `tests/test_http_memory.py` | Add tests for new HTTP endpoints |

### Unchanged

- MemoryLayer ABC — already defines all methods
- NoopMemoryLayer — already has pass/None stubs
- LLM provider interface — no signature changes
- Config files — no new config sections

## Verification

Phase 1c is complete when:

1. All 4 former-501 endpoints return real responses
2. Entity recording dual-writes to PG + graph, queryable via PG
3. Decision recording queues and processes via episode ingestion
4. Relationship queries return edges with entity names via custom Cypher
5. Enricher checks memory before external calls and records entity knowledge
6. Noise filter uses entity/relationship context for scoring (as flattened Facts)
7. Rebuild script replays interaction log and reconstructs the graph
8. Admin reset-graph wipes Neo4j cleanly
9. InteractionEntry stores full card dict + choice_index
10. All existing tests pass (no regressions)

## Out of Scope

- Triage card context enrichment from memory (Phase 1d)
- Multi-user support
- Automatic periodic rebuild (manual CLI only)
- Entity type schemas or validation beyond string types
- Pipeline decision persistence for rebuild (decisions re-learn from new runs)
