# Phase 1c: Entity Knowledge, Decision Recording, and Memory Rebuild — Design Spec

## Context

Phase 1b delivered the memory service with triage interaction recording (structured writes + LLM episode extraction) and preference querying. Four API endpoints return 501 stubs: `record/entity`, `record/decision`, `query/entity`, `query/relationships`. The MemoryLayer ABC already defines methods for all four. Phase 1c fills in these stubs and adds a rebuild mechanism.

## Goals

1. **Entity knowledge** — Record facts about people, repos, teams as graph nodes. Query them to enrich triage context.
2. **Pipeline decision recording** — Record why the pipeline included/dropped items. Full LLM episode extraction to learn patterns like "pipeline consistently drops CI notifications."
3. **Relationship querying** — Query the graph for relationships between entities (emergent from episode extraction, not explicitly created).
4. **Memory rebuild** — CLI script to replay the interaction log from workbench PG into the memory service, reconstructing the graph from scratch.

## Architecture

No new services or databases. Phase 1c extends the existing memory service with new methods on GraphitiMemoryLayer, new endpoints in main.py, and wires HttpMemoryLayer to call them.

```
Workbench Pipeline
  ├─ Enrichment stage ─── POST /record/entity (sync)
  ├─ Engine ──────────── POST /record/decision (queued, async)
  ├─ Noise filter ────── GET /query/preferences (existing)
  │                      GET /query/entity
  │                      GET /query/relationships
  └─ Triage ──────────── POST /record/triage (existing)

Rebuild script ──── reads workbench PG interaction_log
                    POSTs to /record/triage (replays through queue)
```

## Entity Knowledge

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

Implementation: GraphitiMemoryLayer creates graph nodes via `add_triplet()`:
- Source node: `(entity_type:entity_id)` e.g., `(person:alice)`
- For each fact key-value: `(person:alice) --[has_fact {key}]--> (value)`
- Graphiti's entity resolution deduplicates — repeated calls update existing nodes

This is **synchronous** — no queue. Entity writes are simple structured operations without LLM calls, typically called during enrichment (not the hot triage path).

### Read: `GET /query/entity`

Request: `?entity_type=person&entity_id=alice`

Response: `200 OK` with:
```json
{
  "entity_type": "person",
  "entity_id": "alice",
  "facts": {"team": "infra", "role": "tech lead"}
}
```

Or `404` if the entity is not found.

Implementation: GraphitiMemoryLayer searches Graphiti for a node matching `entity_type:entity_id` and returns its connected fact edges.

### Where workbench calls it

The enrichment stage records entity knowledge as a side effect. When the GitHub enricher fetches PR details and sees the author, it calls `memory.record_entity("person", "alice", {repos: [...], recent_prs: [...]})`. This builds entity knowledge incrementally without a separate ingestion pipeline.

HttpMemoryLayer wires `record_entity()` → `POST /record/entity` and `query_entity()` → `GET /query/entity`.

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

The `pending_ingestions` table gets a `type` column (`triage` or `decision`). The worker dispatches to the appropriate handler based on type. Existing triage entries default to `type = 'triage'`. Same retry/dead-letter behavior for both types.

### Where workbench calls it

Already called in `engine.py:110,116`:
```python
await self.memory.record_pipeline_decision(item, "auto_include", f"relevance={relevance}")
await self.memory.record_pipeline_decision(item, "auto_drop", f"relevance={relevance}, reason={reason}")
```

Currently a no-op in HttpMemoryLayer. Phase 1c wires it to `POST /record/decision`.

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

Implementation: GraphitiMemoryLayer searches Graphiti for all edges connected to the entity node, returning them as `Relationship` objects.

### How relationships emerge

No explicit "create relationship" endpoint. Relationships are inferred by Graphiti's LLM extraction from:
1. **Triage episodes** — "user always prioritizes alice's PRs" → relationship between user and alice
2. **Entity facts** — recording that alice works on infra-core creates an implicit relationship
3. **Decision episodes** — "pipeline always includes items from infra-core" → relationship between pipeline and repo

Graphiti handles entity resolution — two mentions of "alice" in different episodes converge to the same node.

## Memory Rebuild

### CLI script: `src/memory/scripts/rebuild.py`

A standalone script that reconstructs the knowledge graph from the interaction log in workbench's PostgreSQL database.

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
   - Constructs a `TriageRecordRequest` from `triage_card_full` + `option_chosen`
   - POSTs to `/record/triage`
4. Polls `GET /admin/queue-depth` between batches to avoid overwhelming the queue
5. Reports progress to stdout: `Replayed 150/500 interactions, queue depth: 3`

**Not part of the memory service process** — runs as a standalone script with its own PG connection.

### Admin endpoints

Two new endpoints for rebuild support and monitoring:

**`POST /admin/reset-graph`** — Wipes all nodes and edges from Neo4j. Returns `200 OK`. Only available when `MEMORY_ADMIN_ENABLED=true` (env var, default false). Returns `403` when disabled.

**`GET /admin/queue-depth`** — Returns `{"depth": N, "dead_letters": M}`. Always available. Useful for rebuild progress monitoring and general health checking.

## API Summary

### New endpoints (replacing 501 stubs)

| Method | Path | Sync/Async | Description |
|--------|------|-----------|-------------|
| POST | `/record/entity` | Sync (200) | Record entity facts via add_triplet |
| POST | `/record/decision` | Async (202) | Queue pipeline decision for episode ingestion |
| GET | `/query/entity` | Sync (200) | Query entity facts |
| GET | `/query/relationships` | Sync (200) | Query entity relationships |

### New admin endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/reset-graph` | Wipe Neo4j graph (requires MEMORY_ADMIN_ENABLED) |
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
| `memory/queue.py` | Add `type` column to pending_ingestions, update enqueue/dequeue |
| `memory/main.py` | Replace 4 stubs with real endpoints, add 2 admin endpoints |
| `scripts/rebuild.py` | New CLI rebuild script |
| `tests/test_graphiti_layer.py` | Add tests for entity/decision/query methods |
| `tests/test_extraction.py` | Add tests for decision narrative formatting |
| `tests/test_rebuild.py` | Test rebuild script logic (mocked HTTP) |

### Workbench (`src/workbench/`)

| File | Change |
|------|--------|
| `memory/http.py` | Wire record_entity, record_pipeline_decision, query_entity, query_relationships to HTTP |
| `tests/test_http_memory.py` | Add tests for new HTTP endpoints |

### Unchanged

- MemoryLayer ABC (`memory/base.py`) — already defines all methods
- NoopMemoryLayer (`memory/noop.py`) — already has pass/None stubs
- Pipeline engine (`engine.py`) — already calls record_pipeline_decision
- Config files — no new config sections needed

## Verification

Phase 1c is complete when:

1. All 4 former-501 endpoints return real responses
2. Entity recording creates graph nodes queryable via `/query/entity`
3. Decision recording queues and processes via episode ingestion
4. Relationship queries return edges connected to entities
5. Rebuild script replays interaction log and reconstructs the graph
6. Admin reset-graph wipes Neo4j cleanly
7. HttpMemoryLayer passes all calls through to the memory service
8. All existing tests pass (no regressions)

## Out of Scope

- Triage card context enrichment from memory (Phase 1d)
- Multi-user support
- Automatic periodic rebuild (manual CLI only)
- Entity type schemas or validation beyond string types
