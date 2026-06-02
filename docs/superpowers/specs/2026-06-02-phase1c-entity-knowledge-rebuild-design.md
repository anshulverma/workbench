# Phase 1c: Entity Knowledge, Decision Recording, and Memory Rebuild — Design Spec

## Context

Phase 1b delivered the memory service with triage interaction recording (structured writes + LLM episode extraction) and preference querying. Four API endpoints return 501 stubs: `record/entity`, `record/decision`, `query/entity`, `query/relationships`. The MemoryLayer ABC already defines methods for all four. Phase 1c fills in these stubs, wires callers in the pipeline, and adds a rebuild mechanism.

## Goals

1. **Entity knowledge** — Record facts about people, repos, teams as graph nodes. Query them to enrich triage context and inform noise filter scoring.
2. **Pipeline decision recording** — Record why the pipeline included/dropped items. Full LLM episode extraction to learn patterns like "pipeline consistently drops CI notifications."
3. **Relationship querying** — Query the graph for relationships between entities (emergent from episode extraction, not explicitly created).
4. **Memory rebuild** — CLI script to replay the interaction log from workbench PG into the memory service, reconstructing the graph from scratch.
5. **Pipeline integration** — Wire entity/relationship queries into both the noise filter and enricher so memory context actually influences scoring and triage cards.

## Architecture

No new services or databases. Phase 1c extends the existing memory service with new methods on GraphitiMemoryLayer, new endpoints in main.py, and wires HttpMemoryLayer to call them. The pipeline gains entity/relationship awareness in both the filter and enrichment stages.

```
Workbench Pipeline
  ├─ Enrichment stage ─── POST /record/entity (sync)
  │                       GET /query/entity (check memory before external calls)
  ├─ Engine ──────────── POST /record/decision (queued, async)
  ├─ Noise filter ────── GET /query/preferences (existing)
  │                      GET /query/entity (flatten to Fact)
  │                      GET /query/relationships (flatten to Fact)
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

**Enrichment stage** — The `ContextEnricher.enrich()` signature changes to accept `MemoryLayer`. The enricher:
1. Checks memory first via `query_entity()` before making external API calls (e.g., if we already know alice's team, skip the `gh` CLI call)
2. Records new entity knowledge via `record_entity()` as a side effect of enrichment

This requires changing the `ContextEnricher` ABC: `async def enrich(self, item, depth, budget, memory)`. `StubEnricher` ignores the memory parameter. `GitHubEnricher` uses it.

The pipeline engine passes `self.memory` when calling `enrich_item()`.

**Noise filter** — `score_and_decide()` queries `query_entity()` for entities mentioned in the item, flattens results to `Fact(content="alice is tech lead on infra team", source="entity")`, and appends them to the preference_facts list passed to `llm.score_relevance()`. No change to the LLM provider interface.

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

The `pending_ingestions` table `CREATE TABLE IF NOT EXISTS` adds a `type TEXT NOT NULL DEFAULT 'triage'` column. The worker dispatches to the appropriate handler based on type. No ALTER TABLE — users with existing data wipe the memory PG data dir (the memory database is derived and rebuildable).

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

The ABC signature stays unchanged. The memory service API takes flat fields. Clean separation — the memory service never knows about the Item model.

### Where workbench calls it

Already called in `engine.py:110,116`. Currently a no-op in HttpMemoryLayer. Phase 1c wires it to `POST /record/decision`.

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

### Where workbench calls it

**Noise filter** — `score_and_decide()` queries `query_relationships()` for entities mentioned in the item, flattens results to `Fact(content="alice reviews infra-core repo", source="relationship")`, and appends to the preference_facts list. Same flattening approach as entity knowledge — no LLM provider interface change.

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
   - Constructs a `TriageRecordRequest` from `triage_card_full` (full card dict) + `choice_index` (integer)
   - POSTs to `/record/triage`
4. Polls `GET /admin/queue-depth` between batches to avoid overwhelming the queue
5. Reports progress to stdout: `Replayed 150/500 interactions, queue depth: 3`

**Not part of the memory service process** — runs as a standalone script with its own PG connection.

### InteractionEntry changes for rebuild support

The interaction log needs two changes to support clean rebuild:

1. **`triage_card_full` stores the full card dict** — Change the triage response handler to store `card.model_dump()` (includes id, options, relevance_score) instead of just `card.card_content`. Existing rows have partial data; the rebuild script handles this gracefully (reconstructs from available fields).

2. **Add `choice_index: int` field** — New integer field storing the numeric choice (1-based index). The triage response handler already knows the index; store it alongside `option_chosen` (the label string). Requires an Alembic migration to add the column to `interaction_log`.

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
| `memory/queue.py` | Add `type` column to CREATE TABLE for pending_ingestions |
| `memory/main.py` | Replace 4 stubs with real endpoints, add 2 admin endpoints, dispatch worker by type |
| `scripts/rebuild.py` | New CLI rebuild script |
| `tests/test_graphiti_layer.py` | Add tests for entity/decision/query methods |
| `tests/test_extraction.py` | Add tests for decision narrative formatting |
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

- MemoryLayer ABC (`memory/base.py`) — already defines all methods
- NoopMemoryLayer (`memory/noop.py`) — already has pass/None stubs
- LLM provider interface — no signature changes (entity/relationship context flattened to Fact)
- Config files — no new config sections needed

## Verification

Phase 1c is complete when:

1. All 4 former-501 endpoints return real responses
2. Entity recording creates graph nodes queryable via `/query/entity`
3. Decision recording queues and processes via episode ingestion
4. Relationship queries return edges connected to entities
5. Enricher checks memory before external calls and records entity knowledge
6. Noise filter uses entity/relationship context for scoring (as flattened Facts)
7. Rebuild script replays interaction log and reconstructs the graph
8. Admin reset-graph wipes Neo4j cleanly
9. HttpMemoryLayer passes all calls through to the memory service
10. InteractionEntry stores full card dict + choice_index
11. All existing tests pass (no regressions)

## Out of Scope

- Triage card context enrichment from memory (Phase 1d — specifically, enriching the card content shown to the user with memory insights)
- Multi-user support
- Automatic periodic rebuild (manual CLI only)
- Entity type schemas or validation beyond string types
