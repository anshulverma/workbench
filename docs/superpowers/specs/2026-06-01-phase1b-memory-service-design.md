# Phase 1b: Memory Service — Design Spec

## Context

Phase 1a delivered the end-to-end triage loop: source polling → ingestion queue → LLM extraction → noise filter → enrichment → triage card → Google Chat → user response → interaction log. The noise filter currently uses only explicit filter rules — it has no learned preferences.

Phase 1b adds a **memory service** that learns user preferences from triage interactions. Every triage response (add todo, skip, mute) flows to the memory service, which extracts preference facts using Graphiti (a temporal knowledge graph library). The noise filter queries these facts to make better scoring decisions over time.

## Architecture

```
┌──────────────────────────────────┐
│  Workbench Server (FastAPI)      │
│                                  │
│  Pipeline Engine                 │
│    ├─ Noise Filter ──────────────┼──── GET /query/preferences ──┐
│    └─ ... (other stages)         │                              │
│                                  │                              │
│  Scheduler + API                 │                              │
│    └─ record_triage() ───────────┼──── POST /record/triage ─────┤
│                                  │     (fire-and-forget)        │
│  HttpMemoryLayer                 │                              │
│    (thin HTTP client)            │                              │
└──────────────────────────────────┘                              │
                                                                  │
                                                    ┌─────────────▼──────────────┐
                                                    │  Memory Service (FastAPI)   │
                                                    │                            │
                                                    │  GraphitiMemoryLayer       │
                                                    │    ├─ Structured writes     │
                                                    │    │  (deterministic)       │
                                                    │    └─ Episode extraction    │
                                                    │       (LLM + custom prompt)│
                                                    │                            │
                                                    │  Graphiti (in-process)      │
                                                    │    └─ AnthropicClient       │
                                                    │       (pluggable via config)│
                                                    └──────┬──────────┬──────────┘
                                                           │          │
                                                    ┌──────▼───┐ ┌────▼──────────┐
                                                    │  Neo4j    │ │  PostgreSQL   │
                                                    │  (graph)  │ │  (graphiti db)│
                                                    └──────────┘ └───────────────┘
```

### Key Principles

- **Workbench never imports Graphiti.** All interaction goes through the memory service's HTTP API. Graphiti, Neo4j, and extraction prompts are internal to the memory service.
- **PostgreSQL remains the source of truth.** The interaction log in PG is the authoritative record. The memory service's graph is derived and rebuildable (Phase 1c).
- **Fire-and-forget writes.** `record_triage()` returns 202 immediately. Extraction happens asynchronously in the memory service. The triage loop is never blocked by LLM extraction.
- **Graceful degradation.** If the memory service is down, `HttpMemoryLayer` catches the error and the noise filter falls back to explicit filter rules only. The pipeline never crashes.
- **Pluggable LLM client.** The memory service uses Graphiti's `AnthropicClient` by default, configured via a `client_class:` field in the memory service config. The client class is loaded via dynamic import (same pattern as workbench's provider registry). For Meta internal, workbench-meta overrides this with a Plugboard-aware client that adds mTLS + api-key-helper. The memory service never knows which LLM backend it's talking to.
- **Config layering.** The memory service supports `--config` + `--override`, same pattern as workbench. OSS uses `memory-config.yml`. Meta internal overlays `memory-config.meta.yml` for Plugboard LLM and credentials.

## Memory Service API

Base URL: `http://localhost:8422` (configurable)

### Phase 1b endpoints

#### `POST /record/triage`

Records a triage interaction for preference extraction.

Request:
```json
{
  "card": {
    "id": "uuid",
    "card_content": {"summary": "...", "source_type": "github", ...},
    "options": [{"label": "Add todo (P1)", "action": "add_todo", ...}, ...],
    "relevance_score": 45
  },
  "response": {
    "card_id": "uuid",
    "choice": 1
  }
}
```

Response: `202 Accepted` with `{"status": "queued"}`

Internally:
1. **Structured writes** — creates deterministic graph nodes and edges:
   - `(user) --[prefers {priority: P1}]--> (pattern: "diffs with blocked reviewers")`
   - `(user) --[avoids]--> (pattern: "CI bot comments")`
   - `(user) --[triaged {action: skip}]--> (item: "PR #42 auth fix")`
2. **Episode ingestion** — formats the interaction as a narrative and calls `graphiti.add_episode()` with a custom extraction prompt for implicit preference patterns.

#### `GET /query/preferences?context={text}`

Searches for preference facts relevant to the given context.

Response:
```json
{
  "facts": [
    {"content": "User always prioritizes diffs where reviewers are blocked", "source": "graphiti", "timestamp": "..."},
    {"content": "User usually skips emails about infrastructure announcements", "source": "graphiti", "timestamp": "..."}
  ]
}
```

Internally: semantic search over both explicit preference edges and LLM-extracted facts in Graphiti.

#### `GET /health`

Response:
```json
{
  "status": "ok",
  "neo4j": "connected",
  "postgres": "connected",
  "graphiti": "initialized"
}
```

#### `GET /facts`

Lists all extracted facts for debugging visibility.

Response:
```json
{
  "facts": [...],
  "total": 42
}
```

### Phase 1c+ endpoints (return 501 in Phase 1b)

- `POST /record/entity`
- `POST /record/decision`
- `GET /query/entity`
- `GET /query/relationships`

## GraphitiMemoryLayer

The core component inside the memory service. Implements the two-layer write strategy:

### Layer 1: Structured Writes (Deterministic)

When `record_triage()` is called, the layer extracts structured data from the card and response and creates explicit graph nodes and edges:

| Response action | Graph effect |
|---|---|
| `add_todo` (any priority) | `(user) --[prefers {priority, action}]--> (pattern: card.summary)` |
| `skip` | `(user) --[avoids {action: skip}]--> (pattern: card.summary)` |
| `mute_pattern` | `(user) --[avoids {action: mute, permanent: true}]--> (pattern: card.summary)` |

Source type is attached to the pattern node: `(pattern {text: "...", source_type: "github"})`.

### Layer 2: Episode Extraction (LLM)

The same interaction is formatted as a narrative text:

```
Triage interaction at 2026-06-01T13:00:00Z:
Source type: github
Item summary: "alice opened PR #100 to add rate limiting to the API gateway"
Relevance score: 45
Options presented: 1. Add todo (P1), 2. Add todo (P2), 3. Skip, 4. Never surface diffs like this
User chose: 1. Add todo (P1)
```

This is passed to `graphiti.add_episode()` with a custom extraction prompt:

```
You are extracting user preference patterns from triage interactions.
Focus on:
- What types of items the user consistently prioritizes or ignores
- Source types, topics, people, or patterns that predict user interest
- Priority signals the user responds to (blocking reviewers, P0 incidents, etc.)

Extract facts in the form: "User [always/never/usually] [action] [item pattern] [when condition]"
Examples:
- "User always prioritizes diffs where reviewers are blocked"
- "User never engages with automated CI notifications"
- "User usually skips emails about infrastructure announcements"
```

Graphiti's LLM call extracts facts, deduplicates against existing facts in the graph, and stores them with temporal metadata.

### Querying

`query_preferences(context)` does a semantic search via Graphiti against both:
- Explicit preference edges (from structured writes)
- LLM-extracted fact nodes (from episode extraction)

Results are merged, deduplicated, and returned as `Fact` objects with content, source, and timestamp.

## LLM Integration

The memory service uses Graphiti's native `AnthropicClient` (from `graphiti-core[anthropic]`) for all LLM calls (fact extraction, entity resolution, semantic search). The client is configured via the memory service's config file and loaded via dynamic import.

### How it works

Graphiti's `Graphiti` class accepts an `llm_client: LLMClient` parameter. The memory service:

1. Reads `llm.client_class` from config (e.g., `memory.llm.DefaultLLMClient`)
2. Dynamically imports and instantiates the class, passing the config
3. Passes the client to `Graphiti(llm_client=client)`

### OSS default

`memory.llm.DefaultLLMClient` wraps Graphiti's `AnthropicClient`:

```python
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.anthropic_client import AnthropicClient

class DefaultLLMClient(AnthropicClient):
    def __init__(self, config):
        llm_config = LLMConfig(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
        )
        super().__init__(config=llm_config)
```

### Meta override (in workbench-meta)

`workbench_meta.memory.PlugboardLLMClient` adds mTLS + api-key-helper:

```python
from anthropic import AsyncAnthropic
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.anthropic_client import AnthropicClient

class PlugboardLLMClient(AnthropicClient):
    def __init__(self, config):
        llm_config = LLMConfig(api_key=..., model=config.model)
        super().__init__(config=llm_config, client=AsyncAnthropic(
            api_key=get_api_key(),
            base_url="https://plugboard.x2p.facebook.net",
            http_client=create_mtls_client(),
        ))
```

## HttpMemoryLayer

New file in workbench: `src/workbench/memory/http.py`. Implements `MemoryLayer` ABC. Thin HTTP client using `httpx.AsyncClient`.

```python
class HttpMemoryLayer(MemoryLayer):
    class ProviderConfig(BaseModel):
        base_url: str = "http://localhost:8422"
        timeout_seconds: int = 5

    async def record_triage(self, card, response):
        # POST /record/triage — fire-and-forget (don't await response body)
        ...

    async def query_preferences(self, context):
        # GET /query/preferences?context=... — returns list[Fact]
        ...

    async def is_available(self):
        # GET /health — returns bool
        ...

    # Phase 1c stubs:
    async def record_entity(self, ...): pass
    async def record_pipeline_decision(self, ...): pass
    async def query_entity(self, ...): return None
    async def query_relationships(self, ...): return []
```

Error handling: all HTTP calls are wrapped in try/except. On failure, methods log the error and return empty results. The pipeline never crashes due to memory service issues.

## File Layout

```
src/
├── workbench/                          (existing)
│   └── memory/
│       ├── base.py                     (existing — MemoryLayer ABC, unchanged)
│       ├── noop.py                     (existing — NoopMemoryLayer, unchanged)
│       └── http.py                     (new — HttpMemoryLayer, thin HTTP client)
│
└── memory/                             (new — standalone FastAPI service)
    ├── __init__.py
    ├── main.py                         (FastAPI app, lifespan, route handlers)
    ├── config.py                       (MemoryConfig — neo4j, pg, llm settings)
    ├── llm.py                          (DefaultLLMClient — wraps Graphiti's AnthropicClient)
    ├── graphiti_layer.py               (GraphitiMemoryLayer — structured writes + episodes)
    ├── extraction.py                   (custom extraction prompt, narrative formatting)
    └── models.py                       (API request/response models)
```

## Configuration

### Memory service config (`memory-config.yml`)

```yaml
server:
  port: 8422

neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: ${oc.env:NEO4J_PASSWORD,neo4j}

storage:
  postgres_dsn: ${oc.env:MEMORY_PG_DSN,postgres://graphiti:graphiti@localhost:5432/graphiti}

llm:
  client_class: memory.llm.DefaultLLMClient
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: https://api.anthropic.com
  model: claude-haiku-4-5-20251001
```

The `client_class` is loaded via dynamic import — same pattern as workbench's provider registry. The memory service never imports workbench code.

### Memory service meta override (`memory-config.meta.yml`)

```yaml
llm:
  client_class: workbench_meta.memory.PlugboardLLMClient
  base_url: https://plugboard.x2p.facebook.net
```

### Workbench config addition (`config.yml`)

```yaml
memory:
  class: workbench.memory.http.HttpMemoryLayer
  base_url: http://localhost:8422
```

### Config layering

The memory service supports the same `--config` + `--override` pattern as workbench:

```bash
memory-serve --config memory-config.yml --override memory-config.meta.yml
```

Merge rules are identical: scalars replace, dicts deep-merge, lists replace.

## Container Setup

### docker-compose.yml additions

```yaml
neo4j:
  image: neo4j:5-community
  network_mode: host
  volumes:
    - ./data/neo4j:/data
  environment:
    NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-neo4j}
    NEO4J_PLUGINS: '["apoc"]'

memory:
  build:
    context: .
    dockerfile: Dockerfile.memory
  network_mode: host
  depends_on:
    - postgres
    - neo4j
  environment:
    NEO4J_URI: bolt://localhost:7687
    NEO4J_PASSWORD: ${NEO4J_PASSWORD:-neo4j}
    MEMORY_PG_DSN: postgres://graphiti:graphiti@localhost:5432/graphiti
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
```

### docker-compose.override.yml (workbench-meta)

Adds overrides for the memory service container, same pattern as the workbench override:

```yaml
memory:
  volumes:
    - ~/workspace/workbench-meta:/opt/workbench-meta:ro
    - ~/workspace/workbench-meta/memory-config.meta.yml:/app/memory-config.override.yml:ro
    - /var/facebook/credentials:/var/facebook/credentials:ro
    - /var/facebook/rootcanal:/var/facebook/rootcanal:ro
  environment:
    USER: ${USER}
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
  entrypoint: ["sh", "-c"]
  command:
    - |
      pip install --no-deps --no-build-isolation -e /opt/workbench-meta &&
      exec uvicorn memory.main:app --host 0.0.0.0 --port 8422
```

### init-db.sh update

Replace the `zep` user/database with `graphiti`:

```sql
CREATE USER graphiti WITH PASSWORD 'graphiti';
CREATE DATABASE graphiti OWNER graphiti;
GRANT ALL PRIVILEGES ON DATABASE graphiti TO graphiti;
```

## Dependencies

### Memory service (`src/memory/`)
- `graphiti-core[anthropic]` — Graphiti library with Anthropic client support
- `neo4j` — Neo4j Python driver (pulled in by graphiti-core)
- `fastapi`, `uvicorn` — HTTP server
- `httpx` — HTTP client
- `asyncpg` — PG connection for Graphiti's vector store
- `omegaconf`, `pyyaml` — config loading

The memory service has its own `pyproject.toml` and does not depend on the `workbench` package. The two are fully independent.

### Workbench additions
- `httpx` (already a dependency) — used by `HttpMemoryLayer`
- No new dependencies

## What Changes in Existing Code

### Modified files
- `init-db.sh` — replace `zep`/`zep` with `graphiti`/`graphiti`
- `docker-compose.yml` — add `neo4j` and `memory` services
- `config.example.yml` — update `memory:` section to use `HttpMemoryLayer`
- `docs/CONTEXT.md` — replace all "Zep" references with "memory service" / "Graphiti"
- `docs/adr/0004-*` — update to reflect Graphiti, not Zep

### Unchanged files
- `src/workbench/memory/base.py` — `MemoryLayer` ABC stays exactly the same
- `src/workbench/memory/noop.py` — `NoopMemoryLayer` stays for testing
- `src/workbench/pipeline/filter.py` — already calls `memory.query_preferences()`
- `src/workbench/pipeline/engine.py` — already calls `memory.record_pipeline_decision()`
- `src/workbench/pipeline/scheduler.py` — already calls `memory.record_triage()`
- `src/workbench/api/triage.py` — already calls `memory.record_triage()`

### New files
- `src/workbench/memory/http.py` — `HttpMemoryLayer`
- `src/memory/` — entire memory service (7 files)
- `Dockerfile.memory` — container build for memory service
- `memory-config.example.yml` — example config for memory service

## Verification

Phase 1b is complete when:

1. `docker compose up` starts workbench + memory + neo4j + postgres (4 containers)
2. Memory service health check returns OK with neo4j + pg connected
3. Submit 5-10 triage responses via the API or Google Chat
4. `GET /facts` on the memory service shows extracted preference facts
5. Submit a new item through the pipeline — the noise filter's `query_preferences()` returns facts from the memory service
6. Relevance scoring visibly changes based on learned preferences (e.g., items matching preferred patterns score higher)
7. Stop the memory service container — workbench pipeline continues working with degraded intelligence (filter rules only, no crash)
8. Restart memory service — preferences are still there (persisted in Neo4j + PG)

## Out of Scope

- Entity knowledge recording and querying (Phase 1c)
- Relationship traversal (Phase 1c)
- Memory rebuild from interaction log (Phase 1c)
- Triage card context enrichment from memory (Phase 1d)
- Multi-user support
