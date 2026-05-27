# Zep Memory Layer — Design Spec

## Context

Workbench's pipeline makes decisions at every stage — what to extract, what's relevant, what context to gather, how to present triage cards. Today these decisions use either explicit filter rules or a hand-rolled 3-layer preference system (interaction log → LLM batch synthesis → preference summary markdown). This works but is limited: preferences are a flat summary, there's no entity knowledge graph, and context enrichment starts from scratch on every run.

Zep is an open-source memory layer for LLM applications. It provides automatic fact extraction, knowledge graph construction, and temporal reasoning. By integrating Zep, the pipeline accumulates knowledge over time — learning preferences from triage responses, building a graph of people/diffs/tasks/relationships, and making every stage smarter with each interaction.

## Architecture

Zep runs as a self-hosted service on the devgpu alongside the Workbench server. Both run in containers managed by Podman.

```
┌─────────────────────────────────┐
│  Workbench Server (FastAPI)     │
│                                 │
│  Pipeline Engine                │
│    ├─ Extraction (Claude API)   │
│    ├─ Noise Filter ◄────────────┼──── queries Zep for preferences
│    ├─ Enrichment ◄──────────────┼──── queries Zep before external APIs
│    └─ Triage Card Gen ◄────────┼──── pulls relationship context from Zep
│                                 │
│  Dual-write layer               │
│    ├─ SQLite (source of truth)  │
│    └─ Zep (knowledge extraction)│
└────────────┬────────────────────┘
             │
    ┌────────▼────────┐
    │  Zep Server      │
    │  (self-hosted)   │
    │                  │
    │  Knowledge Graph │
    │  Fact Extraction │
    │  User Memory     │
    └────────┬─────────┘
             │
    ┌────────▼────────┐
    │  PostgreSQL      │
    │  + pgvector      │
    └─────────────────┘
```

### Key Principle

SQLite remains the source of truth for all structured data (items, triage cards, jobs, filter rules). Zep is additive — it extracts knowledge from the same data and makes it queryable in ways SQLite can't (semantic search, knowledge graph traversal, temporal fact reasoning). If Zep is down, the pipeline runs with degraded intelligence but doesn't break.

## Deployment

All services run via Podman Compose on the devgpu:

```yaml
# docker-compose.yml (Podman-compatible)
services:
  workbench:          # FastAPI server
    build: ./server
    network_mode: host
    volumes:
      - workbench-data:/data    # SQLite file
    environment:
      - WORKBENCH_ZEP_URL=http://localhost:8000
      - WORKBENCH_STORAGE_BACKEND=sqlite
      - WORKBENCH_API_TOKEN=${WORKBENCH_API_TOKEN}
      - WORKBENCH_PORT=8421

  zep:                # Zep memory server
    image: ghcr.io/getzep/zep:latest
    network_mode: host
    environment:
      - ZEP_STORE_POSTGRES_DSN=postgres://zep:zep@localhost:5432/zep
      - ZEP_LLM_ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ZEP_LLM_ANTHROPIC_BASE_URL=https://plugboard.x2p.facebook.net
      - ZEP_SERVER_PORT=8000

  zep-postgres:       # PostgreSQL + pgvector for Zep
    image: ghcr.io/getzep/postgres:latest
    network_mode: host
    volumes:
      - zep-pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=zep
      - POSTGRES_PASSWORD=zep
      - POSTGRES_DB=zep

volumes:
  workbench-data:
  zep-pgdata:
```

Pull images (first time only — devserver requires proxy for external registries):
```bash
with-proxy podman pull ghcr.io/getzep/zep:latest
with-proxy podman pull ghcr.io/getzep/postgres:latest
```

Managed by systemd user service:
```bash
podman compose up -d        # start all services
podman compose logs -f      # tail logs
podman compose down         # stop all services
```

Zep uses the same Claude API via Plugboard for its fact extraction — same `ANTHROPIC_BASE_URL` and API key as the Workbench pipeline.

## What Flows Into Zep

### 1. Triage Interactions (highest value)

Every triage card + user response becomes a Zep message in a long-running conversation. Zep auto-extracts preference facts:
- "User always prioritizes diffs where reviewers are blocked"
- "User drops emails from infrastructure-announcements group"
- "User treats SEVs for auth service as P0"

### 2. Entity Knowledge (accumulated context)

When the pipeline processes a raw item, key entities get stored in Zep's knowledge graph:
- People: "@alice is on the auth team, reports to @bob"
- Diffs: "D12345 is a refactor of auth middleware, authored by @alice"
- Tasks: "T98765 is a subtask of T98760 (Auth hardening Q3)"
- Relationships: "@alice authored D12345 which relates to T98765"

### 3. Pipeline Decisions (learning signal)

When the noise filter auto-includes or auto-drops an item, that decision is logged to Zep. This reinforces patterns like "items about auth migration are always included."

### What Does NOT Go Into Zep

- Raw email/diff content (too large, low signal-to-noise)
- Job status tracking (purely operational)
- Source adapter configs (infrastructure, not knowledge)

## MemoryLayer Interface

Sits alongside the repository pattern, not inside it:

```python
class MemoryLayer(ABC):
    async def record_triage(self, card: TriageCard, response: TriageResponse) -> None: ...
    async def record_entity(self, entity_type: str, entity_id: str, facts: dict) -> None: ...
    async def record_pipeline_decision(self, item: Item, decision: str, reason: str) -> None: ...
    async def query_preferences(self, context: str) -> list[Fact]: ...
    async def query_entity(self, entity_type: str, entity_id: str) -> EntityKnowledge | None: ...
    async def query_relationships(self, entity_id: str) -> list[Relationship]: ...
    async def is_available(self) -> bool: ...
```

Implementations:
- `ZepMemoryLayer` — calls the Zep Python SDK
- `NoopMemoryLayer` — returns empty results (testing, Zep-disabled mode)

## Pipeline Integration

Each stage uses a "Zep-first, fallback-gracefully" pattern:

### Noise Filter (Stage 3)
- Queries `memory.query_preferences(context)` for relevant preference facts
- Facts are included as LLM context alongside explicit filter rules
- **Fallback:** Uses only explicit filter rules from SQLite if Zep unavailable

### Context Enrichment (Stage 4)
- Queries `memory.query_entity()` and `memory.query_relationships()` before calling external APIs
- If Zep knows the entity, skip the external API call
- Newly fetched context from external APIs is written back to Zep via `memory.record_entity()`
- **Fallback:** Goes straight to external APIs (or StubEnricher)

### Triage Card Generation (Stage 5)
- Queries Zep for relationship context: "What else has the user seen about this topic recently?"
- Adds contextual lines like "3rd email about Q3 planning this week"
- **Fallback:** Generates card without relationship context

## What the Preference System Becomes

### Stays
- `interaction_log` table — still append-only, still source of truth for raw interaction data
- `filter_rules` table — explicit deterministic rules still live in SQLite

### Goes
- `preferences` table — replaced by Zep's knowledge graph
- `PreferenceStore` repository interface — removed
- `server/pipeline/preferences.py` — synthesis job removed from scheduler
- Scheduler's "daily preference regeneration" task — Zep handles this continuously

### Changes
- Noise filter queries `memory.query_preferences()` instead of reading preference summary
- `/api/preferences` returns Zep's current fact list
- `/api/preferences/seed` writes seed facts into Zep
- New endpoint: `/api/memory/facts` — proxies Zep's fact list for debugging visibility
- New endpoint: `POST /api/memory/rebuild` — replays interaction log through Zep to rebuild knowledge graph

## Dual-Write Pattern

The pipeline engine holds both `stores` (SQLite repositories) and `memory` (MemoryLayer):

```python
# After recording a triage response:
await stores.triage.record_response(card_id, response)     # source of truth
await stores.interactions.append(interaction_entry)          # source of truth
await memory.record_triage(card, response)                   # knowledge extraction
```

If `memory.record_triage()` fails, it logs the error and continues. No transaction coupling between SQLite and Zep.

## Implementation Phases

### Phase 1a: Core triage loop (no Zep)
Build the pipeline end-to-end with `NoopMemoryLayer`. SQLite storage, Claude API extraction, basic noise filter with explicit filter rules only, template triage cards via Google Chat. Get the loop working.

### Phase 1b: Zep for preferences
- Stand up Zep via Podman
- Implement `ZepMemoryLayer`
- Wire up `record_triage()` — every triage response flows to Zep
- Wire up `query_preferences()` in the noise filter
- Remove the old preference synthesis job
- Verify: after 20-30 triage responses, noise filter makes noticeably better decisions

### Phase 1c: Zep for entity knowledge
- Wire up `record_entity()` — extracted entities flow to Zep
- Wire up `query_entity()` and `query_relationships()` in enrichment
- Verify: Zep answers entity questions from accumulated knowledge, reducing external API calls

### Phase 1d: Zep for triage card context
- Triage card generation queries Zep for relationship context
- Cards get richer contextual lines
- Verify: triage cards show accumulated relationship context

## Data Durability

Zep's knowledge graph is always rebuildable from the interaction log (SQLite/XDB), which is the source of truth. Two mechanisms:

**Rebuild from source of truth:** A `rebuild_memory()` function replays all interaction log entries through `memory.record_triage()`, reconstructing the knowledge graph from scratch. Available as an API endpoint (`POST /api/memory/rebuild`) and CLI command. Used after Zep data loss or when migrating to a new devserver.

**Periodic PostgreSQL backup:** A cron job dumps Zep's PostgreSQL to a compressed file on a configurable schedule (default: daily). Stored locally and optionally synced to Manifold or another durable location. Faster recovery than a full rebuild — restore the dump instead of replaying months of interactions.

## Verification

1. `podman compose up -d` — all three services start (workbench, zep, zep-postgres)
2. `NoopMemoryLayer` — pipeline works end-to-end without Zep
3. Switch to `ZepMemoryLayer` — triage responses flow to Zep, facts extracted
4. After 20+ triage responses, `GET /api/memory/facts` shows extracted preferences
5. Noise filter uses Zep facts — scoring visibly changes based on learned preferences
6. Zep down — pipeline degrades gracefully (uses filter rules only, no crash)
7. Entity knowledge — after processing diffs, Zep knows "@alice authored D12345"
8. Enrichment queries Zep first — fewer external API calls over time
9. Triage cards show relationship context from Zep
