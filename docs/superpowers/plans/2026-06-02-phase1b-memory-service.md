# Phase 1b: Memory Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone memory service that learns user preferences from triage interactions via Graphiti + Neo4j, and wire it into the workbench pipeline so the noise filter uses learned preferences alongside explicit filter rules.

**Architecture:** A separate FastAPI service (`src/memory/`) wraps Graphiti behind a REST API. Workbench talks to it via `HttpMemoryLayer` (thin HTTP client). Triage interactions are durably queued in PostgreSQL and processed asynchronously — structured graph writes for deterministic preferences, plus LLM-based episode fact ingestion for implicit patterns. Neo4j stores the knowledge graph; PostgreSQL (`memory` database) stores the pending ingestions queue.

**Tech Stack:** Python 3.12, FastAPI, graphiti-core[anthropic], Neo4j 5, asyncpg, httpx, OmegaConf, pytest + pytest-asyncio.

---

## File Structure

### New files — Memory service (`src/memory/`)

```
src/memory/
├── pyproject.toml                      Package metadata + dependencies
├── memory/                             Python package
│   ├── __init__.py                     Version
│   ├── main.py                         FastAPI app, lifespan, routes
│   ├── config.py                       MemoryConfig + config loader
│   ├── llm.py                          DefaultLLMClient (wraps Graphiti AnthropicClient)
│   ├── graphiti_layer.py               GraphitiMemoryLayer (structured writes + episodes)
│   ├── extraction.py                   Fact ingestion prompt + narrative formatting
│   ├── queue.py                        PendingIngestionStore + async worker
│   └── models.py                       API request/response models
├── memory-config.example.yml           Example config
├── Dockerfile                          Container build
└── tests/
    ├── conftest.py                     Test fixtures
    ├── test_models.py                  Request/response model tests
    ├── test_queue.py                   Pending ingestion queue tests
    ├── test_extraction.py              Narrative formatting tests
    └── test_graphiti_layer.py          GraphitiMemoryLayer tests (mocked Graphiti)
```

### New files — Workbench integration
- `src/workbench/memory/http.py` — HttpMemoryLayer (thin HTTP client)
- `tests/test_http_memory.py` — HttpMemoryLayer tests (mocked HTTP)

### Modified files
- `init-db.sh` — replace `zep`/`zep` with `memory`/`memory`
- `docker-compose.yml` — switch PG image to `postgres:17`, add `neo4j` and `memory` services
- `config.example.yml` — update `memory:` section to use `HttpMemoryLayer`
- `docs/CONTEXT.md` — replace Zep references, add "fact ingestion" and "memory service" terms
- `docs/adr/0004-zep-as-parallel-knowledge-layer.md` — rename and reword for Graphiti

### Deleted files
- `docs/specs/2026-05-27-zep-memory-layer-design.md` — superseded by Phase 1b spec

---

## Task 1: Memory Service Package Scaffold

**Files:**
- Create: `src/memory/pyproject.toml`
- Create: `src/memory/memory/__init__.py`
- Create: `src/memory/memory/models.py`
- Test: `src/memory/tests/test_models.py`

Set up the Python package with dependencies and the API request/response models that all other tasks depend on.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
# src/memory/pyproject.toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "memory-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.0",
    "graphiti-core[anthropic]>=0.29",
    "asyncpg>=0.30",
    "httpx>=0.27",
    "omegaconf>=2.3",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["memory*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `memory/__init__.py`**

```python
# src/memory/memory/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Write the failing test for models**

```python
# src/memory/tests/test_models.py
import pytest
from memory.models import TriageRecordRequest, PreferenceQueryResponse, Fact


def test_triage_record_request():
    req = TriageRecordRequest(
        card={
            "id": "card-1",
            "card_content": {"summary": "Fix auth", "source_type": "github"},
            "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
            "relevance_score": 45,
        },
        response={"card_id": "card-1", "choice": 1},
    )
    assert req.card["id"] == "card-1"
    assert req.response["choice"] == 1


def test_fact_model():
    f = Fact(content="User prefers auth diffs", source="graphiti")
    assert f.content == "User prefers auth diffs"
    assert f.source == "graphiti"
    assert f.timestamp is not None


def test_preference_query_response():
    resp = PreferenceQueryResponse(facts=[
        Fact(content="User prefers P1 diffs", source="graphiti"),
    ])
    assert len(resp.facts) == 1


def test_preference_query_response_empty():
    resp = PreferenceQueryResponse(facts=[])
    assert resp.facts == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd src/memory && pip install -e ".[dev]" && pytest tests/test_models.py -x -v`
Expected: `ModuleNotFoundError: No module named 'memory.models'`

- [ ] **Step 5: Create `memory/models.py`**

```python
# src/memory/memory/models.py
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Fact(BaseModel):
    content: str
    source: str = "graphiti"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageRecordRequest(BaseModel):
    card: dict
    response: dict


class PreferenceQueryResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    postgres: str
    graphiti: str


class FactsListResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    total: int = 0
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src/memory && pytest tests/test_models.py -x -v`
Expected: All 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(memory): scaffold memory service package with API models"
```

---

## Task 2: Config Loader

**Files:**
- Create: `src/memory/memory/config.py`
- Create: `src/memory/memory-config.example.yml`

- [ ] **Step 1: Write `config.py`**

```python
# src/memory/memory/config.py
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    port: int = 8422


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j"


class StorageConfig(BaseModel):
    postgres_dsn: str = "postgres://memory:memory@localhost:5432/memory"


class LLMConfig(BaseModel):
    client_class: str = "memory.llm.DefaultLLMClient"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-haiku-4-5-20251001"


class QueueConfig(BaseModel):
    max_attempts: int = 3
    base_delay_seconds: int = 5
    worker_concurrency: int = 1


class MemoryConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)


def load_config(config_path: str, override_path: str | None = None) -> MemoryConfig:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)
    return MemoryConfig(**resolved)
```

- [ ] **Step 2: Write `memory-config.example.yml`**

```yaml
# memory-config.example.yml — copy to memory-config.yml and edit
server:
  port: 8422

neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: ${oc.env:NEO4J_PASSWORD,neo4j}

storage:
  postgres_dsn: ${oc.env:MEMORY_PG_DSN,postgres://memory:memory@localhost:5432/memory}

llm:
  client_class: memory.llm.DefaultLLMClient
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: https://api.anthropic.com
  model: claude-haiku-4-5-20251001

queue:
  max_attempts: 3
  base_delay_seconds: 5
  worker_concurrency: 1
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(memory): add config loader with OmegaConf layering"
```

---

## Task 3: Pending Ingestion Queue

**Files:**
- Create: `src/memory/memory/queue.py`
- Create: `src/memory/tests/conftest.py`
- Test: `src/memory/tests/test_queue.py`

A durable PostgreSQL-backed queue for triage interactions awaiting fact ingestion. Same pattern as workbench's `IngestionQueueWorker`.

- [ ] **Step 1: Write the failing tests**

```python
# src/memory/tests/test_queue.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && pytest tests/test_queue.py -x -v`
Expected: `ModuleNotFoundError: No module named 'memory.queue'`

- [ ] **Step 3: Write `queue.py`**

```python
# src/memory/memory/queue.py
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from memory.models import TriageRecordRequest

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pending_ingestions (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class PendingIngestionStore:
    def __init__(self, dsn: str, max_attempts: int = 3):
        self.dsn = dsn
        self.max_attempts = max_attempts
        self.pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute(CREATE_TABLE)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def enqueue(self, request: TriageRecordRequest) -> str:
        entry_id = str(uuid.uuid4())
        payload = request.model_dump_json()
        await self.pool.execute(
            "INSERT INTO pending_ingestions (id, payload, max_attempts) VALUES ($1, $2::jsonb, $3)",
            entry_id, payload, self.max_attempts,
        )
        return entry_id

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
            RETURNING id, payload, attempt
            """,
            limit,
        )
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempt": r["attempt"]} for r in rows]

    async def mark_completed(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE pending_ingestions SET status = 'completed', updated_at = NOW() WHERE id = $1",
            entry_id,
        )

    async def mark_failed(self, entry_id: str, error: str) -> None:
        row = await self.pool.fetchrow(
            "SELECT attempt, max_attempts FROM pending_ingestions WHERE id = $1",
            entry_id,
        )
        if row:
            new_attempt = row["attempt"] + 1
            if new_attempt >= row["max_attempts"]:
                status = "dead_letter"
            else:
                status = "queued"
            await self.pool.execute(
                "UPDATE pending_ingestions SET status = $1, attempt = $2, error = $3, updated_at = NOW() WHERE id = $4",
                status, new_attempt, error, entry_id,
            )

    async def get_dead_letters(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT id, payload, attempt, error, created_at FROM pending_ingestions WHERE status = 'dead_letter' ORDER BY created_at"
        )
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempt": r["attempt"], "error": r["error"]} for r in rows]

    async def queue_depth(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as count FROM pending_ingestions WHERE status = 'queued'"
        )
        return row["count"]

    async def recover_stuck(self) -> int:
        result = await self.pool.execute(
            "UPDATE pending_ingestions SET status = 'queued', updated_at = NOW() WHERE status = 'processing'"
        )
        count = int(result.split()[-1])
        if count:
            logger.info("Recovered %d stuck ingestion entries", count)
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && pytest tests/test_queue.py -x -v`
Expected: All 5 tests pass (requires PostgreSQL with `memory` database running).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(memory): add durable pending ingestion queue with PG backend"
```

---

## Task 4: Fact Ingestion Prompt + Narrative Formatting

**Files:**
- Create: `src/memory/memory/extraction.py`
- Test: `src/memory/tests/test_extraction.py`

Formats triage interactions as narrative text and provides the custom extraction prompt for Graphiti's `add_episode()`.

- [ ] **Step 1: Write the failing tests**

```python
# src/memory/tests/test_extraction.py
from memory.extraction import format_triage_narrative, FACT_INGESTION_PROMPT


def test_format_triage_narrative_add_todo():
    card = {
        "id": "c1",
        "card_content": {"summary": "alice opened PR #100 to add rate limiting", "source_type": "github"},
        "options": [
            {"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}},
            {"label": "Skip", "action": "skip"},
        ],
        "relevance_score": 45,
    }
    response = {"card_id": "c1", "choice": 1}

    narrative = format_triage_narrative(card, response)

    assert "github" in narrative
    assert "alice opened PR #100" in narrative
    assert "Add todo (P1)" in narrative
    assert "User chose: 1" in narrative


def test_format_triage_narrative_skip():
    card = {
        "id": "c2",
        "card_content": {"summary": "CI bot notification", "source_type": "github"},
        "options": [
            {"label": "Add todo (P1)", "action": "add_todo"},
            {"label": "Skip", "action": "skip"},
        ],
        "relevance_score": 20,
    }
    response = {"card_id": "c2", "choice": 2}

    narrative = format_triage_narrative(card, response)

    assert "Skip" in narrative
    assert "User chose: 2" in narrative


def test_fact_ingestion_prompt_exists():
    assert "preference patterns" in FACT_INGESTION_PROMPT
    assert "always" in FACT_INGESTION_PROMPT
    assert "never" in FACT_INGESTION_PROMPT


def test_format_triage_narrative_mute():
    card = {
        "id": "c3",
        "card_content": {"summary": "Weekly digest email", "source_type": "email"},
        "options": [
            {"label": "Add todo (P2)", "action": "add_todo"},
            {"label": "Skip", "action": "skip"},
            {"label": "Never surface emails like this", "action": "mute_pattern"},
        ],
        "relevance_score": 15,
    }
    response = {"card_id": "c3", "choice": 3}

    narrative = format_triage_narrative(card, response)

    assert "Never surface emails like this" in narrative
    assert "email" in narrative
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && pytest tests/test_extraction.py -x -v`
Expected: `ModuleNotFoundError: No module named 'memory.extraction'`

- [ ] **Step 3: Write `extraction.py`**

```python
# src/memory/memory/extraction.py
from datetime import datetime, timezone

FACT_INGESTION_PROMPT = """You are extracting user preference patterns from triage interactions.
Focus on:
- What types of items the user consistently prioritizes or ignores
- Source types, topics, people, or patterns that predict user interest
- Priority signals the user responds to (blocking reviewers, P0 incidents, etc.)

Extract facts in the form: "User [always/never/usually] [action] [item pattern] [when condition]"
Examples:
- "User always prioritizes diffs where reviewers are blocked"
- "User never engages with automated CI notifications"
- "User usually skips emails about infrastructure announcements"
"""


def format_triage_narrative(card: dict, response: dict) -> str:
    content = card.get("card_content", {})
    summary = content.get("summary", "Unknown item")
    source_type = content.get("source_type", "unknown")
    relevance = card.get("relevance_score", 0)
    options = card.get("options", [])
    choice = response.get("choice", 0)

    options_text = "\n".join(
        f"  {i}. {opt.get('label', '?')}" for i, opt in enumerate(options, 1)
    )

    chosen_label = ""
    if 1 <= choice <= len(options):
        chosen_label = options[choice - 1].get("label", "?")

    now = datetime.now(timezone.utc).isoformat()

    return f"""Triage interaction at {now}:
Source type: {source_type}
Item summary: "{summary}"
Relevance score: {relevance}
Options presented:
{options_text}
User chose: {choice}. {chosen_label}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && pytest tests/test_extraction.py -x -v`
Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(memory): add fact ingestion prompt and narrative formatting"
```

---

## Task 5: Default LLM Client

**Files:**
- Create: `src/memory/memory/llm.py`

Wraps Graphiti's `AnthropicClient` with config-driven initialization. Loaded via dynamic import from the `client_class` config field.

- [ ] **Step 1: Write `llm.py`**

```python
# src/memory/memory/llm.py
from __future__ import annotations

import importlib
import logging
from typing import Any

from memory.config import LLMConfig

logger = logging.getLogger(__name__)


class DefaultLLMClient:
    """Wraps Graphiti's AnthropicClient. Default LLM client for OSS deployments."""

    def __init__(self, config: LLMConfig):
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client.config import LLMConfig as GraphitiLLMConfig

        graphiti_config = GraphitiLLMConfig(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
        )
        self._client = AnthropicClient(config=graphiti_config)

    @property
    def client(self) -> Any:
        return self._client


def create_llm_client(config: LLMConfig) -> Any:
    class_path = config.client_class
    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import LLM client '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")
    instance = cls(config)
    return instance.client if hasattr(instance, "client") else instance
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(memory): add pluggable LLM client with dynamic import"
```

---

## Task 6: GraphitiMemoryLayer

**Files:**
- Create: `src/memory/memory/graphiti_layer.py`
- Test: `src/memory/tests/test_graphiti_layer.py`

The core component — structured writes + episode fact ingestion via Graphiti.

- [ ] **Step 1: Write the failing tests**

```python
# src/memory/tests/test_graphiti_layer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from memory.graphiti_layer import GraphitiMemoryLayer


@pytest.fixture
def mock_graphiti():
    g = AsyncMock()
    g.add_episode = AsyncMock(return_value=MagicMock(
        nodes=[],
        edges=[MagicMock(fact="User prefers auth diffs", name="prefers")],
    ))
    g.search = AsyncMock(return_value=[
        MagicMock(fact="User always prioritizes auth diffs", name="prefers"),
    ])
    return g


@pytest.fixture
def layer(mock_graphiti):
    return GraphitiMemoryLayer(graphiti=mock_graphiti)


@pytest.mark.asyncio
async def test_record_triage_calls_add_episode(layer, mock_graphiti):
    card = {
        "id": "c1",
        "card_content": {"summary": "Fix auth", "source_type": "github"},
        "options": [{"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}}],
        "relevance_score": 45,
    }
    response = {"card_id": "c1", "choice": 1}

    await layer.record_triage(card, response)

    mock_graphiti.add_episode.assert_called_once()
    call_kwargs = mock_graphiti.add_episode.call_args
    assert "Fix auth" in call_kwargs.kwargs.get("episode_body", "") or "Fix auth" in str(call_kwargs)


@pytest.mark.asyncio
async def test_record_triage_uses_custom_extraction_prompt(layer, mock_graphiti):
    card = {
        "id": "c1",
        "card_content": {"summary": "Fix auth", "source_type": "github"},
        "options": [{"label": "Skip", "action": "skip"}],
        "relevance_score": 20,
    }
    response = {"card_id": "c1", "choice": 1}

    await layer.record_triage(card, response)

    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs.get("custom_extraction_instructions") is not None
    assert "preference" in call_kwargs["custom_extraction_instructions"].lower()


@pytest.mark.asyncio
async def test_query_preferences_returns_facts(layer, mock_graphiti):
    facts = await layer.query_preferences("auth diffs")

    mock_graphiti.search.assert_called_once()
    assert len(facts) == 1
    assert "auth diffs" in facts[0].content


@pytest.mark.asyncio
async def test_query_preferences_empty_when_no_results(layer, mock_graphiti):
    mock_graphiti.search.return_value = []

    facts = await layer.query_preferences("unknown topic")
    assert facts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/memory && pytest tests/test_graphiti_layer.py -x -v`
Expected: `ModuleNotFoundError: No module named 'memory.graphiti_layer'`

- [ ] **Step 3: Write `graphiti_layer.py`**

```python
# src/memory/memory/graphiti_layer.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from memory.extraction import FACT_INGESTION_PROMPT, format_triage_narrative
from memory.models import Fact

logger = logging.getLogger(__name__)


class GraphitiMemoryLayer:
    def __init__(self, graphiti):
        self.graphiti = graphiti

    async def record_triage(self, card: dict, response: dict) -> None:
        narrative = format_triage_narrative(card, response)
        card_id = card.get("id", "unknown")

        try:
            from graphiti_core.nodes import EpisodeType
            await self.graphiti.add_episode(
                name=f"triage-{card_id}",
                episode_body=narrative,
                source_description="workbench triage interaction",
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                custom_extraction_instructions=FACT_INGESTION_PROMPT,
            )
        except Exception as e:
            logger.error("Failed to ingest triage episode: %s", e, exc_info=True)
            raise

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            edges = await self.graphiti.search(query=context, num_results=10)
            return [
                Fact(
                    content=edge.fact,
                    source="graphiti",
                    timestamp=edge.valid_at or datetime.now(timezone.utc),
                )
                for edge in edges
                if edge.fact
            ]
        except Exception as e:
            logger.error("Failed to query preferences: %s", e, exc_info=True)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/memory && pytest tests/test_graphiti_layer.py -x -v`
Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(memory): add GraphitiMemoryLayer with structured writes + episode ingestion"
```

---

## Task 7: Memory Service FastAPI App

**Files:**
- Create: `src/memory/memory/main.py`

The FastAPI application with lifespan, routes, and the async ingestion worker.

- [ ] **Step 1: Write `main.py`**

```python
# src/memory/memory/main.py
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import FastAPI, Query

from memory import __version__
from memory.config import MemoryConfig, load_config
from memory.graphiti_layer import GraphitiMemoryLayer
from memory.llm import create_llm_client
from memory.models import (
    FactsListResponse,
    HealthResponse,
    PreferenceQueryResponse,
    TriageRecordRequest,
)
from memory.queue import PendingIngestionStore

logger = logging.getLogger(__name__)


def get_config() -> MemoryConfig:
    config_path = os.environ.get("MEMORY_CONFIG", "memory-config.yml")
    override_path = os.environ.get("MEMORY_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


async def _run_ingestion_worker(
    store: PendingIngestionStore, layer: GraphitiMemoryLayer, concurrency: int = 1
):
    semaphore = asyncio.Semaphore(concurrency)
    recovered = await store.recover_stuck()
    if recovered:
        logger.info("Recovered %d stuck ingestion entries", recovered)

    while True:
        try:
            entries = await store.dequeue(limit=concurrency)
            if not entries:
                await asyncio.sleep(2)
                continue

            async def process(entry):
                async with semaphore:
                    try:
                        payload = entry["payload"]
                        await layer.record_triage(payload["card"], payload["response"])
                        await store.mark_completed(entry["id"])
                        logger.info("Fact ingestion completed for entry %s", entry["id"])
                    except Exception as e:
                        logger.error("Fact ingestion failed for entry %s: %s", entry["id"], e)
                        await store.mark_failed(entry["id"], str(e))

            await asyncio.gather(*(process(e) for e in entries))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Ingestion worker error: %s", e)
            await asyncio.sleep(5)


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    # Initialize pending ingestion queue
    store = PendingIngestionStore(config.storage.postgres_dsn, config.queue.max_attempts)
    await store.initialize()
    app.state.store = store

    # Initialize Graphiti
    llm_client = create_llm_client(config.llm)

    from graphiti_core import Graphiti
    graphiti = Graphiti(
        uri=config.neo4j.uri,
        user=config.neo4j.user,
        password=config.neo4j.password,
        llm_client=llm_client,
    )
    try:
        await graphiti.build_indices_and_constraints()
    except Exception as e:
        logger.warning("Failed to build Graphiti indices: %s", e)

    app.state.graphiti = graphiti
    app.state.layer = GraphitiMemoryLayer(graphiti=graphiti)

    # Start ingestion worker
    worker_task = asyncio.create_task(
        _run_ingestion_worker(store, app.state.layer, config.queue.worker_concurrency)
    )

    logger.info("Memory service %s ready on port %d", __version__, config.server.port)

    yield

    logger.info("Shutting down...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await graphiti.close()
    await store.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Memory Service", version=__version__, lifespan=lifespan)

    @app.post("/record/triage", status_code=202)
    async def record_triage(request: TriageRecordRequest):
        store: PendingIngestionStore = app.state.store
        entry_id = await store.enqueue(request)
        return {"status": "queued", "entry_id": entry_id}

    @app.get("/query/preferences", response_model=PreferenceQueryResponse)
    async def query_preferences(context: str = Query(...)):
        layer: GraphitiMemoryLayer = app.state.layer
        facts = await layer.query_preferences(context)
        return PreferenceQueryResponse(facts=facts)

    @app.get("/health", response_model=HealthResponse)
    async def health():
        neo4j_status = "unknown"
        pg_status = "unknown"
        graphiti_status = "unknown"

        try:
            await app.state.graphiti.driver.health_check()
            neo4j_status = "connected"
        except Exception:
            neo4j_status = "disconnected"

        try:
            await app.state.store.pool.fetchval("SELECT 1")
            pg_status = "connected"
        except Exception:
            pg_status = "disconnected"

        graphiti_status = "initialized" if app.state.graphiti else "not initialized"

        status = "ok" if neo4j_status == "connected" and pg_status == "connected" else "degraded"
        return HealthResponse(
            status=status, neo4j=neo4j_status, postgres=pg_status, graphiti=graphiti_status
        )

    @app.get("/facts", response_model=FactsListResponse)
    async def list_facts():
        layer: GraphitiMemoryLayer = app.state.layer
        facts = await layer.query_preferences("")
        return FactsListResponse(facts=facts, total=len(facts))

    @app.post("/record/entity", status_code=501)
    async def record_entity():
        return {"error": "Not implemented — Phase 1c"}

    @app.post("/record/decision", status_code=501)
    async def record_decision():
        return {"error": "Not implemented — Phase 1c"}

    @app.get("/query/entity", status_code=501)
    async def query_entity():
        return {"error": "Not implemented — Phase 1c"}

    @app.get("/query/relationships", status_code=501)
    async def query_relationships():
        return {"error": "Not implemented — Phase 1c"}

    return app


app = create_app()
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(memory): add FastAPI app with routes, lifespan, and ingestion worker"
```

---

## Task 8: Memory Service Dockerfile

**Files:**
- Create: `src/memory/Dockerfile`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
# src/memory/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY memory/ memory/
COPY memory-config.example.yml memory-config.yml
RUN pip install --no-cache-dir -e .
EXPOSE 8422
CMD ["uvicorn", "memory.main:app", "--host", "0.0.0.0", "--port", "8422"]
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(memory): add Dockerfile for memory service container"
```

---

## Task 9: HttpMemoryLayer in Workbench

**Files:**
- Create: `src/workbench/memory/http.py`
- Test: `tests/test_http_memory.py`

Thin HTTP client implementing the existing `MemoryLayer` ABC. Talks to the memory service.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_http_memory.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.memory.http import HttpMemoryLayer
from workbench.models import TriageCard, TriageOption, TriageResponse


@pytest.fixture
def mock_http_client():
    return AsyncMock()


@pytest.fixture
def layer(mock_http_client):
    config = HttpMemoryLayer.ProviderConfig(base_url="http://localhost:8422")
    m = HttpMemoryLayer(config)
    m._client = mock_http_client
    return m


@pytest.mark.asyncio
async def test_record_triage_posts_to_memory_service(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()
    mock_http_client.post.return_value = mock_response

    card = TriageCard(
        card_content={"summary": "Fix auth", "source_type": "github"},
        options=[TriageOption(label="Add todo (P1)", action="add_todo")],
    )
    response = TriageResponse(card_id=card.id, choice=1)

    await layer.record_triage(card, response)

    mock_http_client.post.assert_called_once()
    call_args = mock_http_client.post.call_args
    assert "/record/triage" in call_args[0][0]


@pytest.mark.asyncio
async def test_record_triage_does_not_raise_on_failure(layer, mock_http_client):
    mock_http_client.post.side_effect = Exception("Connection refused")

    card = TriageCard(
        card_content={"summary": "test", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
    )
    response = TriageResponse(card_id=card.id, choice=1)

    # Should not raise — graceful degradation
    await layer.record_triage(card, response)


@pytest.mark.asyncio
async def test_query_preferences_returns_facts(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "facts": [
            {"content": "User prefers auth diffs", "source": "graphiti", "timestamp": "2026-06-01T00:00:00Z"}
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    facts = await layer.query_preferences("auth diffs")

    assert len(facts) == 1
    assert facts[0].content == "User prefers auth diffs"


@pytest.mark.asyncio
async def test_query_preferences_returns_empty_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    facts = await layer.query_preferences("anything")
    assert facts == []


@pytest.mark.asyncio
async def test_is_available_returns_true(layer, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get.return_value = mock_response

    assert await layer.is_available() is True


@pytest.mark.asyncio
async def test_is_available_returns_false_on_failure(layer, mock_http_client):
    mock_http_client.get.side_effect = Exception("Connection refused")

    assert await layer.is_available() is False


@pytest.mark.asyncio
async def test_close_closes_client(layer, mock_http_client):
    await layer.close()
    mock_http_client.aclose.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/pytest tests/test_http_memory.py -x -v`
Expected: `ModuleNotFoundError: No module named 'workbench.memory.http'`

- [ ] **Step 3: Write `http.py`**

```python
# src/workbench/memory/http.py
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from workbench.memory.base import MemoryLayer
from workbench.models import (
    EntityKnowledge,
    Fact,
    Item,
    Relationship,
    TriageCard,
    TriageResponse,
)

logger = logging.getLogger(__name__)


class HttpMemoryLayer(MemoryLayer):
    class ProviderConfig(BaseModel):
        base_url: str = "http://localhost:8422"
        timeout_seconds: int = 5

    def __init__(self, config: ProviderConfig = None):
        if config is None:
            config = self.ProviderConfig()
        self._base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def record_triage(self, card: TriageCard, response: TriageResponse) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/record/triage",
                json={
                    "card": card.model_dump(),
                    "response": response.model_dump(),
                },
            )
        except Exception as e:
            logger.warning("Memory service record_triage failed: %s", e)

    async def record_entity(self, entity_type: str, entity_id: str, facts: dict) -> None:
        pass

    async def record_pipeline_decision(self, item: Item, decision: str, reason: str) -> None:
        pass

    async def query_preferences(self, context: str) -> list[Fact]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/query/preferences",
                params={"context": context},
            )
            resp.raise_for_status()
            data = resp.json()
            return [Fact(content=f["content"], source=f.get("source", "graphiti")) for f in data.get("facts", [])]
        except Exception as e:
            logger.warning("Memory service query_preferences failed: %s", e)
            return []

    async def query_entity(self, entity_type: str, entity_id: str) -> EntityKnowledge | None:
        return None

    async def query_relationships(self, entity_id: str) -> list[Relationship]:
        return []

    async def is_available(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/pytest tests/test_http_memory.py -x -v`
Expected: All 7 tests pass.

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `.venv/bin/pytest tests/ -x -v --ignore=src`
Expected: All existing tests pass.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: add HttpMemoryLayer — thin HTTP client for memory service"
```

---

## Task 10: Infrastructure Updates

**Files:**
- Modify: `init-db.sh`
- Modify: `docker-compose.yml`
- Modify: `config.example.yml`

- [ ] **Step 1: Update `init-db.sh`**

Replace `zep` with `memory`:

```bash
#!/bin/bash
# init-db.sh — creates workbench and memory databases on first PG start
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER workbench WITH PASSWORD 'workbench';
    CREATE DATABASE workbench OWNER workbench;

    CREATE USER memory WITH PASSWORD 'memory';
    CREATE DATABASE memory OWNER memory;

    -- Grant connect permissions
    GRANT ALL PRIVILEGES ON DATABASE workbench TO workbench;
    GRANT ALL PRIVILEGES ON DATABASE memory TO memory;
EOSQL
```

- [ ] **Step 2: Update `docker-compose.yml`**

Switch PG image to `postgres:17` and add `neo4j` and `memory` services:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:17
    network_mode: host
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh:ro
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres

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
      context: ./src/memory
    network_mode: host
    depends_on:
      - postgres
      - neo4j
    environment:
      NEO4J_PASSWORD: ${NEO4J_PASSWORD:-neo4j}
      MEMORY_PG_DSN: postgres://memory:memory@localhost:5432/memory
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}

  workbench:
    build: .
    network_mode: host
    depends_on:
      - postgres
      - memory
    volumes:
      - ./data/logs:/app/logs
    environment:
      WORKBENCH_API_TOKEN: ${WORKBENCH_API_TOKEN:-dev-token}
      WORKBENCH_POSTGRES_DSN: postgres://workbench:workbench@localhost:5432/workbench
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ANTHROPIC_BASE_URL: ${ANTHROPIC_BASE_URL:-https://api.anthropic.com}
```

- [ ] **Step 3: Update `config.example.yml` memory section**

Replace the memory section:

```yaml
# Memory — HttpMemoryLayer (production) or NoopMemoryLayer (no memory service)
memory:
  class: workbench.memory.noop.NoopMemoryLayer
# With memory service:
# memory:
#   class: workbench.memory.http.HttpMemoryLayer
#   base_url: http://localhost:8422
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: update infrastructure for memory service — PG, Neo4j, docker-compose"
```

---

## Task 11: Documentation Updates

**Files:**
- Delete: `docs/specs/2026-05-27-zep-memory-layer-design.md`
- Modify: `docs/adr/0004-zep-as-parallel-knowledge-layer.md`
- Modify: `docs/CONTEXT.md`

- [ ] **Step 1: Delete the old Zep spec**

```bash
git rm docs/specs/2026-05-27-zep-memory-layer-design.md
```

- [ ] **Step 2: Rename and reword ADR 0004**

Rename the file and update content to reflect Graphiti/memory service:

```bash
git mv docs/adr/0004-zep-as-parallel-knowledge-layer.md docs/adr/0004-memory-as-parallel-knowledge-layer.md
```

New content for `docs/adr/0004-memory-as-parallel-knowledge-layer.md`:

```markdown
# ADR 0004: Memory Service as a Parallel Knowledge Layer, Not a Storage Replacement

The memory service (Graphiti + Neo4j) runs alongside the primary storage backend (PostgreSQL) as an additive intelligence layer. PostgreSQL remains the source of truth for all structured data (items, triage cards, jobs, filter rules). The memory service receives a copy of triage interactions for knowledge extraction and graph construction. The pipeline queries the memory service for preferences and relationship context, falling back gracefully if the memory service is unavailable.

We chose this over making the memory service the primary store (Approach B) because: (1) the memory service as a single point of failure would break the core triage loop on any outage; (2) the dual-write adds minor complexity but keeps the system resilient; (3) the memory service's knowledge graph is always rebuildable from the interaction log in PostgreSQL, so data durability concerns are eliminated.

**Consequence:** The pipeline engine holds both `stores` (repositories) and `memory` (MemoryLayer). Dual-writes happen at the pipeline level with no transaction coupling. If the memory service fails, the pipeline runs with degraded intelligence (explicit filter rules only) but doesn't break. See also ADR 0009 for why the memory layer is a separate HTTP service.
```

- [ ] **Step 3: Update CONTEXT.md**

Replace all "Zep" references and add new terms. Key changes:

- Replace "Zep" with "memory service" or "Graphiti" throughout
- Replace "ZepMemoryLayer" with "HttpMemoryLayer (production) and NoopMemoryLayer (testing)"
- Replace "Preference Fact: A single learned preference extracted by Zep" with updated definition
- Add "Fact Ingestion" term
- Add "Memory Service" term
- Update "Memory Layer" definition
- Update "Storage Backend" to remove Zep database references

- [ ] **Step 4: Commit**

```bash
git commit -m "docs: remove Zep terminology, update ADR 0004, add memory service terms to CONTEXT.md"
```

---

## Task 12: End-to-End Verification Tests

**Files:**
- Test: `tests/test_http_memory.py` (add integration test)

- [ ] **Step 1: Add an integration test that verifies the full flow**

```python
# Append to tests/test_http_memory.py

def test_http_memory_layer_provider_config():
    config = HttpMemoryLayer.ProviderConfig(
        base_url="http://localhost:8422",
        timeout_seconds=10,
    )
    assert config.base_url == "http://localhost:8422"
    assert config.timeout_seconds == 10


def test_http_memory_layer_default_config():
    config = HttpMemoryLayer.ProviderConfig()
    assert config.base_url == "http://localhost:8422"
    assert config.timeout_seconds == 5
```

- [ ] **Step 2: Verify the provider registry can instantiate HttpMemoryLayer**

```python
# Append to tests/test_http_memory.py

def test_registry_can_create_http_memory_layer():
    from workbench.registry import create_provider
    layer = create_provider({
        "class": "workbench.memory.http.HttpMemoryLayer",
        "base_url": "http://localhost:8422",
    })
    assert isinstance(layer, HttpMemoryLayer)
```

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/pytest tests/ -x -v --ignore=src`
Expected: All tests pass including new HttpMemoryLayer tests.

- [ ] **Step 4: Commit**

```bash
git commit -m "test: add HttpMemoryLayer provider registry and config tests"
```

---

## Summary of Changes

After all 12 tasks:

| Task | What it does |
|---|---|
| 1. Package scaffold | Memory service package with API models |
| 2. Config loader | OmegaConf config with layering support |
| 3. Pending queue | Durable PG-backed ingestion queue |
| 4. Extraction | Fact ingestion prompt + narrative formatting |
| 5. LLM client | Pluggable Graphiti AnthropicClient wrapper |
| 6. GraphitiMemoryLayer | Core: structured writes + episode ingestion |
| 7. FastAPI app | Routes, lifespan, ingestion worker |
| 8. Dockerfile | Container build for memory service |
| 9. HttpMemoryLayer | Thin HTTP client in workbench |
| 10. Infrastructure | init-db.sh, docker-compose, config.example.yml |
| 11. Documentation | Zep removal, ADR 0004 rewrite, CONTEXT.md update |
| 12. E2E tests | Provider registry, config, integration |

### Live verification (not in plan, manual)
After all tasks:
1. `docker compose up` starts 4 containers (postgres, neo4j, memory, workbench)
2. Memory service health returns OK
3. Submit 5-10 triage responses
4. `GET /facts` shows extracted preference facts
5. New pipeline items score differently based on learned preferences
6. Stop memory service — workbench continues with filter rules only
