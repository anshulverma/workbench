# Phase 1a: Core Triage Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working end-to-end triage loop: ingest raw content → extract items via Claude → filter → generate triage card → send to Google Chat → receive response → store result. All running in Podman on a devgpu.

**Architecture:** FastAPI server in a Podman container with SQLite storage (repository pattern), Claude API via Plugboard for LLM calls, Google Chat (Jarvis bot) for triage cards with text-based replies. NoopMemoryLayer as placeholder for Zep (Phase 1b).

**Tech Stack:** Python 3.12, FastAPI, SQLite (aiosqlite), Anthropic Python SDK, Pydantic, APScheduler, Podman Compose

**Specs:**
- `docs/specs/2026-05-21-workbench-design.md` — main spec
- `docs/specs/2026-05-27-zep-memory-layer-design.md` — Zep spec (Phase 1b)
- `docs/plans/_stale/` — old step specs for reference on schema details

---

## File Structure

```
docker-compose.yml                 -- Podman Compose (workbench only for 1a, zep added in 1b)
server/
  Dockerfile
  requirements.txt
  main.py                          -- FastAPI app, mounts routers, startup/shutdown
  config.py                        -- Settings from env vars (Pydantic)
  models.py                        -- Pydantic domain models (Item, TriageCard, RawItem, etc.)
  storage/
    base.py                        -- all repository interface ABCs
    factory.py                     -- create_stores() from config
    sqlite/
      __init__.py
      connection.py                -- SQLite connection, schema init, WAL mode
      items.py                     -- SqliteItemStore
      triage.py                    -- SqliteTriageStore
      plans.py                     -- SqlitePlanStore
      interactions.py              -- SqliteInteractionStore
      filter_rules.py              -- SqliteFilterRuleStore
      enrichment.py                -- SqliteEnrichmentTraceStore
      sources.py                   -- SqliteSourceConfigStore
      processed.py                 -- SqliteProcessedStore
      config.py                    -- SqliteConfigStore
      jobs.py                      -- SqliteJobStore
  memory/
    base.py                        -- MemoryLayer ABC
    noop.py                        -- NoopMemoryLayer
  providers/
    llm/
      base.py                      -- LLMProvider ABC
      claude.py                    -- ClaudeProvider (Anthropic SDK via Plugboard)
    messenger/
      base.py                      -- Messenger ABC
      google_chat.py               -- GoogleChatMessenger (google_api.py)
    source/
      base.py                      -- SourceAdapter ABC
      phabricator.py               -- PhabricatorAdapter (Conduit API)
      email_gmail.py               -- GmailAdapter (Google API proxy)
    doc_reader/
      base.py                      -- DocReader ABC
      google_docs.py               -- GoogleDocsReader
    enrichment/
      base.py                      -- ContextEnricher ABC
      stub.py                      -- StubEnricher (returns empty)
  pipeline/
    engine.py                      -- PipelineEngine orchestration
    extraction.py                  -- extract_items() wrapping LLM
    filter.py                      -- score_and_decide() noise filter
    enrichment.py                  -- enrich_item() with budget
    triage.py                      -- generate_card() + template options
    scheduler.py                   -- APScheduler setup, triage queue
  api/
    items.py                       -- GET/PATCH/DELETE items
    triage.py                      -- GET pending, POST respond
    process.py                     -- POST /api/process
    filter_rules.py                -- GET/POST filter rules
    sources.py                     -- CRUD source configs
    config.py                      -- GET/PATCH config
    health.py                      -- GET /health
    memory.py                      -- GET /api/memory/facts (stub for 1a)
    jobs.py                        -- GET /api/jobs/{job_id}
  auth.py                          -- bearer token middleware
tests/
  conftest.py                      -- fixtures (test stores, test config)
  test_models.py
  test_storage.py
  test_pipeline.py
  test_api.py
  test_filter.py
```

---

## Task 1: Podman Stack + Server Skeleton

**Files:**
- Create: `docker-compose.yml`, `server/Dockerfile`, `server/requirements.txt`, `server/main.py`, `server/config.py`, `server/auth.py`

- [ ] **Step 1: Write server config**

```python
# server/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    storage_backend: str = "sqlite"
    sqlite_path: str = "/data/workbench.db"
    api_token: str = "dev-token-change-me"
    port: int = 8421
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://plugboard.x2p.facebook.net"
    zep_url: str = ""
    gchat_space_id: str = ""
    google_api_script: str = "/app/google_api.py"
    poll_interval_minutes: int = 15
    triage_timeout_minutes: int = 30
    morning_briefing_hour: int = 9
    debug: bool = False

    class Config:
        env_prefix = "WORKBENCH_"
```

- [ ] **Step 2: Write bearer token auth middleware**

```python
# server/auth.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {self.token}":
            raise HTTPException(status_code=401, detail="Invalid token")
        return await call_next(request)
```

- [ ] **Step 3: Write FastAPI entrypoint**

```python
# server/main.py
from fastapi import FastAPI
from server.config import Settings
from server.auth import BearerTokenMiddleware

settings = Settings()
app = FastAPI(title="Workbench", version="0.1.0")
app.add_middleware(BearerTokenMiddleware, token=settings.api_token)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
```

- [ ] **Step 4: Write Dockerfile**

```dockerfile
# server/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8421
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8421"]
```

- [ ] **Step 5: Write requirements.txt**

```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.0
pydantic-settings>=2.0
aiosqlite>=0.20
anthropic>=0.40
apscheduler>=3.10
httpx>=0.27
```

- [ ] **Step 6: Write docker-compose.yml**

```yaml
# docker-compose.yml
services:
  workbench:
    build: ./server
    network_mode: host
    volumes:
      - workbench-data:/data
    environment:
      - WORKBENCH_API_TOKEN=${WORKBENCH_API_TOKEN:-dev-token}
      - WORKBENCH_STORAGE_BACKEND=sqlite
      - WORKBENCH_SQLITE_PATH=/data/workbench.db
      - WORKBENCH_ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - WORKBENCH_ANTHROPIC_BASE_URL=https://plugboard.x2p.facebook.net
      - WORKBENCH_GCHAT_SPACE_ID=${GCHAT_SPACE_ID}
      - WORKBENCH_PORT=8421

volumes:
  workbench-data:
```

- [ ] **Step 7: Build and verify**

Run:
```bash
podman compose build
podman compose up -d
curl http://localhost:8421/health
```
Expected: `{"status":"ok"}`

Run with auth:
```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/health
```
Expected: `{"status":"ok"}`

Run without auth on a non-health endpoint (will fail until endpoints exist, but verify middleware):
```bash
curl http://localhost:8421/api/items
```
Expected: 401

- [ ] **Step 8: Commit**

```bash
sl commit -m "Add server skeleton: FastAPI, Podman, bearer token auth, health endpoint"
```

---

## Task 2: Domain Models

**Files:**
- Create: `server/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write domain models**

```python
# server/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
import uuid

class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    PENDING = "pending"

class ItemStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"
    ARCHIVED = "archived"

class ItemCategory(str, Enum):
    ACTION_ITEM = "action_item"
    MEETING = "meeting"
    INFORMATIONAL = "informational"

class ItemOrigin(str, Enum):
    AUTO_INCLUDED = "auto_included"
    TRIAGED = "triaged"
    MANUAL = "manual"

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobTrigger(str, Enum):
    MANUAL = "manual"
    POLL = "poll"

class RawItem(BaseModel):
    id: str
    source_type: str
    source_label: str
    raw_text: str

class ExtractedItem(BaseModel):
    summary: str
    category: ItemCategory
    source_context: str
    raw_item: RawItem

class Item(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str
    source_id: str
    summary: str
    category: ItemCategory
    origin: ItemOrigin
    priority: Priority
    status: ItemStatus = ItemStatus.ACTIVE
    raw_data: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ItemUpdate(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    summary: str | None = None

class ItemFilters(BaseModel):
    priority: Priority | None = None
    status: ItemStatus | None = None
    source_type: str | None = None
    category: ItemCategory | None = None

class TriageOption(BaseModel):
    label: str
    action: str
    details: dict = Field(default_factory=dict)

class TriageCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str | None = None
    card_content: dict = Field(default_factory=dict)
    options: list[TriageOption] = Field(default_factory=list)
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    response: str | None = None

class TriageResponse(BaseModel):
    card_id: str
    choice: int
    raw_text: str | None = None

class FilterRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str | None = None
    pattern: str
    action: str  # "include" or "drop"
    priority: Priority | None = None
    created_from_interaction_id: str | None = None

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
    todo_created: dict | None = None
    enrichment_depth: str = "none"
    enrichment_calls: int = 0
    enrichment_time_ms: int = 0

class EnrichmentTrace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str
    depth: str
    calls_made: int
    time_ms: int
    context_retrieved: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TraceFilters(BaseModel):
    item_id: str | None = None
    since: datetime | None = None

class SourceConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    adapter_type: str
    config: dict = Field(default_factory=dict)
    schedule: str = "*/15 * * * *"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SourceConfigUpdate(BaseModel):
    config: dict | None = None
    schedule: str | None = None
    enabled: bool | None = None

class PipelineJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger: JobTrigger
    status: JobStatus = JobStatus.PENDING
    input_hash: str = ""
    items_extracted: int = 0
    items_included: int = 0
    items_triaged: int = 0
    items_dropped: int = 0
    items_failed: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

class Plan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    status: str = "draft"
    content: str = ""
    sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PlanFilters(BaseModel):
    status: str | None = None

class PlanUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    content: str | None = None

class PreferenceSummary(BaseModel):
    content: str
    cursor_position: int
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class EnrichmentBudget(BaseModel):
    max_api_calls: int = 3
    max_seconds: int = 10

class Fact(BaseModel):
    content: str
    source: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class EntityKnowledge(BaseModel):
    entity_type: str
    entity_id: str
    facts: dict = Field(default_factory=dict)

class Relationship(BaseModel):
    from_entity: str
    to_entity: str
    relation: str
```

- [ ] **Step 2: Write model tests**

```python
# tests/test_models.py
import pytest
from server.models import (
    Item, ItemStatus, ItemCategory, ItemOrigin, Priority,
    RawItem, ExtractedItem, TriageCard, TriageOption,
    FilterRule, InteractionEntry, PipelineJob, JobStatus, JobTrigger,
)

def test_item_defaults():
    item = Item(
        source_type="diff",
        source_id="D12345",
        summary="Review auth middleware",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P1,
    )
    assert item.status == ItemStatus.ACTIVE
    assert item.id  # auto-generated
    assert item.created_at

def test_raw_item():
    raw = RawItem(id="D12345_123", source_type="diff", source_label="D12345", raw_text="content")
    assert raw.source_type == "diff"

def test_extracted_item():
    raw = RawItem(id="1", source_type="email", source_label="test", raw_text="hi")
    extracted = ExtractedItem(summary="Test", category=ItemCategory.ACTION_ITEM, source_context="ctx", raw_item=raw)
    assert extracted.category == ItemCategory.ACTION_ITEM

def test_triage_card_with_options():
    card = TriageCard(
        card_content={"summary": "Review D12345"},
        options=[
            TriageOption(label="Add review todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    assert len(card.options) == 2
    assert card.responded_at is None

def test_pipeline_job_defaults():
    job = PipelineJob(trigger=JobTrigger.MANUAL)
    assert job.status == JobStatus.PENDING
    assert job.items_extracted == 0

def test_filter_rule():
    rule = FilterRule(pattern="CI bot comments on diffs", action="drop")
    assert rule.source_type is None
    assert rule.action == "drop"
```

- [ ] **Step 3: Run tests**

Run: `cd /home/anshulverma/workspace/workbench && python -m pytest tests/test_models.py -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
sl commit -m "Add Pydantic domain models for all entities"
```

---

## Task 3: Storage Layer (Interfaces)

**Files:**
- Create: `server/storage/__init__.py`, `server/storage/base.py`, `server/storage/factory.py`

- [ ] **Step 1: Write repository interfaces**

```python
# server/storage/base.py
from abc import ABC, abstractmethod
from server.models import (
    Item, ItemFilters, ItemUpdate,
    TriageCard, TriageResponse,
    Plan, PlanFilters, PlanUpdate,
    InteractionEntry,
    FilterRule,
    EnrichmentTrace, TraceFilters,
    SourceConfig, SourceConfigUpdate,
    PipelineJob,
)

class ItemStore(ABC):
    @abstractmethod
    async def get_items(self, filters: ItemFilters) -> list[Item]: ...
    @abstractmethod
    async def get_item(self, item_id: str) -> Item | None: ...
    @abstractmethod
    async def save_item(self, item: Item) -> Item: ...
    @abstractmethod
    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item: ...
    @abstractmethod
    async def archive_item(self, item_id: str) -> None: ...

class TriageStore(ABC):
    @abstractmethod
    async def get_pending(self) -> list[TriageCard]: ...
    @abstractmethod
    async def save_card(self, card: TriageCard) -> TriageCard: ...
    @abstractmethod
    async def record_response(self, card_id: str, response: TriageResponse) -> None: ...
    @abstractmethod
    async def get_card(self, card_id: str) -> TriageCard | None: ...

class PlanStore(ABC):
    @abstractmethod
    async def get_plans(self, filters: PlanFilters) -> list[Plan]: ...
    @abstractmethod
    async def save_plan(self, plan: Plan) -> Plan: ...
    @abstractmethod
    async def update_plan(self, plan_id: str, updates: PlanUpdate) -> Plan: ...

class InteractionStore(ABC):
    @abstractmethod
    async def append(self, entry: InteractionEntry) -> None: ...
    @abstractmethod
    async def get_since(self, cursor: int, limit: int) -> list[InteractionEntry]: ...
    @abstractmethod
    async def count(self) -> int: ...
    @abstractmethod
    async def get_all(self) -> list[InteractionEntry]: ...

class FilterRuleStore(ABC):
    @abstractmethod
    async def get_rules(self) -> list[FilterRule]: ...
    @abstractmethod
    async def add_rule(self, rule: FilterRule) -> FilterRule: ...
    @abstractmethod
    async def get_source_rules(self, source_type: str) -> list[FilterRule]: ...

class EnrichmentTraceStore(ABC):
    @abstractmethod
    async def log_trace(self, trace: EnrichmentTrace) -> None: ...
    @abstractmethod
    async def get_traces(self, filters: TraceFilters) -> list[EnrichmentTrace]: ...

class SourceConfigStore(ABC):
    @abstractmethod
    async def get_sources(self) -> list[SourceConfig]: ...
    @abstractmethod
    async def save_source(self, source: SourceConfig) -> SourceConfig: ...
    @abstractmethod
    async def update_source(self, source_id: str, updates: SourceConfigUpdate) -> SourceConfig: ...
    @abstractmethod
    async def delete_source(self, source_id: str) -> None: ...

class ProcessedStore(ABC):
    @abstractmethod
    async def is_processed(self, source_type: str, source_id: str) -> bool: ...
    @abstractmethod
    async def mark_processed(self, source_type: str, source_id: str) -> None: ...

class ConfigStore(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...
    @abstractmethod
    async def set(self, key: str, value: str) -> None: ...
    @abstractmethod
    async def get_all(self) -> dict[str, str]: ...

class JobStore(ABC):
    @abstractmethod
    async def save_job(self, job: PipelineJob) -> PipelineJob: ...
    @abstractmethod
    async def get_job(self, job_id: str) -> PipelineJob | None: ...
    @abstractmethod
    async def update_job(self, job: PipelineJob) -> None: ...

class Stores:
    """Container for all repository instances."""
    def __init__(
        self,
        items: ItemStore,
        triage: TriageStore,
        plans: PlanStore,
        interactions: InteractionStore,
        filter_rules: FilterRuleStore,
        enrichment: EnrichmentTraceStore,
        sources: SourceConfigStore,
        processed: ProcessedStore,
        config: ConfigStore,
        jobs: JobStore,
    ):
        self.items = items
        self.triage = triage
        self.plans = plans
        self.interactions = interactions
        self.filter_rules = filter_rules
        self.enrichment = enrichment
        self.sources = sources
        self.processed = processed
        self.config = config
        self.jobs = jobs
```

- [ ] **Step 2: Write storage factory**

```python
# server/storage/factory.py
from server.config import Settings
from server.storage.base import Stores

async def create_stores(settings: Settings) -> Stores:
    if settings.storage_backend == "sqlite":
        from server.storage.sqlite import create_sqlite_stores
        return await create_sqlite_stores(settings.sqlite_path)
    raise ValueError(f"Unknown storage backend: {settings.storage_backend}")
```

- [ ] **Step 3: Commit**

```bash
sl commit -m "Add storage layer interfaces and factory"
```

---

## Task 4: SQLite Storage Implementation

**Files:**
- Create: `server/storage/sqlite/__init__.py`, `server/storage/sqlite/connection.py`, `server/storage/sqlite/items.py`, `server/storage/sqlite/triage.py`, `server/storage/sqlite/plans.py`, `server/storage/sqlite/interactions.py`, `server/storage/sqlite/filter_rules.py`, `server/storage/sqlite/enrichment.py`, `server/storage/sqlite/sources.py`, `server/storage/sqlite/processed.py`, `server/storage/sqlite/config.py`, `server/storage/sqlite/jobs.py`
- Test: `tests/test_storage.py`

This is the largest task. Each store module follows the same pattern: receive a connection, implement the ABC methods with SQL.

- [ ] **Step 1: Write SQLite connection and schema init**

```python
# server/storage/sqlite/connection.py
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    origin TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    raw_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_status_priority ON items(status, priority);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    content TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_cards (
    id TEXT PRIMARY KEY,
    item_id TEXT,
    card_content TEXT NOT NULL DEFAULT '{}',
    options TEXT NOT NULL DEFAULT '[]',
    sent_at TEXT,
    responded_at TEXT,
    response TEXT
);
CREATE INDEX IF NOT EXISTS idx_triage_pending ON triage_cards(responded_at);

CREATE TABLE IF NOT EXISTS interaction_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_id TEXT,
    item_summary TEXT NOT NULL,
    triage_card_full TEXT NOT NULL DEFAULT '{}',
    enrichment_context TEXT NOT NULL DEFAULT '{}',
    options_presented TEXT NOT NULL DEFAULT '[]',
    option_chosen TEXT NOT NULL DEFAULT '',
    todo_created TEXT,
    enrichment_depth TEXT NOT NULL DEFAULT 'none',
    enrichment_calls INTEGER NOT NULL DEFAULT 0,
    enrichment_time_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS filter_rules (
    id TEXT PRIMARY KEY,
    source_type TEXT,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    priority TEXT,
    created_from_interaction_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enrichment_trace (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    depth TEXT NOT NULL,
    calls_made INTEGER NOT NULL,
    time_ms INTEGER NOT NULL,
    context_retrieved TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source_type, source_id)
);

CREATE TABLE IF NOT EXISTS source_configs (
    id TEXT PRIMARY KEY,
    adapter_type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    schedule TEXT NOT NULL DEFAULT '*/15 * * * *',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_hash TEXT NOT NULL DEFAULT '',
    items_extracted INTEGER NOT NULL DEFAULT 0,
    items_included INTEGER NOT NULL DEFAULT 0,
    items_triaged INTEGER NOT NULL DEFAULT 0,
    items_dropped INTEGER NOT NULL DEFAULT 0,
    items_failed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

async def create_connection(db_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.executescript(SCHEMA)
    await db.commit()
    return db
```

- [ ] **Step 2: Implement SqliteItemStore**

```python
# server/storage/sqlite/items.py
import json
from server.storage.base import ItemStore
from server.models import Item, ItemFilters, ItemUpdate, ItemStatus

class SqliteItemStore(ItemStore):
    def __init__(self, db):
        self.db = db

    async def get_items(self, filters: ItemFilters) -> list[Item]:
        query = "SELECT * FROM items WHERE 1=1"
        params = []
        if filters.status:
            query += " AND status = ?"
            params.append(filters.status.value)
        if filters.priority:
            query += " AND priority = ?"
            params.append(filters.priority.value)
        if filters.source_type:
            query += " AND source_type = ?"
            params.append(filters.source_type)
        if filters.category:
            query += " AND category = ?"
            params.append(filters.category.value)
        query += " ORDER BY created_at DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        cursor = await self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return self._row_to_item(row) if row else None

    async def save_item(self, item: Item) -> Item:
        await self.db.execute(
            "INSERT INTO items (id, source_type, source_id, summary, category, origin, priority, status, raw_data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.source_type, item.source_id, item.summary, item.category.value, item.origin.value, item.priority.value, item.status.value, json.dumps(item.raw_data), item.created_at.isoformat(), item.updated_at.isoformat()),
        )
        await self.db.commit()
        return item

    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item:
        sets, params = [], []
        if updates.priority is not None:
            sets.append("priority = ?")
            params.append(updates.priority.value)
        if updates.status is not None:
            sets.append("status = ?")
            params.append(updates.status.value)
        if updates.summary is not None:
            sets.append("summary = ?")
            params.append(updates.summary)
        sets.append("updated_at = datetime('now')")
        params.append(item_id)
        await self.db.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params)
        await self.db.commit()
        return await self.get_item(item_id)

    async def archive_item(self, item_id: str) -> None:
        await self.db.execute("UPDATE items SET status = 'archived', updated_at = datetime('now') WHERE id = ?", (item_id,))
        await self.db.commit()

    def _row_to_item(self, row) -> Item:
        return Item(
            id=row["id"], source_type=row["source_type"], source_id=row["source_id"],
            summary=row["summary"], category=row["category"], origin=row["origin"],
            priority=row["priority"], status=row["status"],
            raw_data=json.loads(row["raw_data"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
```

- [ ] **Step 3: Implement remaining SQLite stores**

Each follows the same pattern as `SqliteItemStore`. Implement:
- `SqliteTriageStore` in `server/storage/sqlite/triage.py`
- `SqlitePlanStore` in `server/storage/sqlite/plans.py`
- `SqliteInteractionStore` in `server/storage/sqlite/interactions.py`
- `SqliteFilterRuleStore` in `server/storage/sqlite/filter_rules.py`
- `SqliteEnrichmentTraceStore` in `server/storage/sqlite/enrichment.py`
- `SqliteSourceConfigStore` in `server/storage/sqlite/sources.py`
- `SqliteProcessedStore` in `server/storage/sqlite/processed.py`
- `SqliteConfigStore` in `server/storage/sqlite/config.py`
- `SqliteJobStore` in `server/storage/sqlite/jobs.py`

Use `docs/plans/_stale/02-database-schema.md` for column details. All stores receive the `db` connection in `__init__`. JSON columns are stored as TEXT and parsed with `json.loads/json.dumps`.

- [ ] **Step 4: Write __init__.py to create all stores**

```python
# server/storage/sqlite/__init__.py
from server.storage.base import Stores
from server.storage.sqlite.connection import create_connection
from server.storage.sqlite.items import SqliteItemStore
from server.storage.sqlite.triage import SqliteTriageStore
from server.storage.sqlite.plans import SqlitePlanStore
from server.storage.sqlite.interactions import SqliteInteractionStore
from server.storage.sqlite.filter_rules import SqliteFilterRuleStore
from server.storage.sqlite.enrichment import SqliteEnrichmentTraceStore
from server.storage.sqlite.sources import SqliteSourceConfigStore
from server.storage.sqlite.processed import SqliteProcessedStore
from server.storage.sqlite.config import SqliteConfigStore
from server.storage.sqlite.jobs import SqliteJobStore

async def create_sqlite_stores(db_path: str) -> Stores:
    db = await create_connection(db_path)
    return Stores(
        items=SqliteItemStore(db),
        triage=SqliteTriageStore(db),
        plans=SqlitePlanStore(db),
        interactions=SqliteInteractionStore(db),
        filter_rules=SqliteFilterRuleStore(db),
        enrichment=SqliteEnrichmentTraceStore(db),
        sources=SqliteSourceConfigStore(db),
        processed=SqliteProcessedStore(db),
        config=SqliteConfigStore(db),
        jobs=SqliteJobStore(db),
    )
```

- [ ] **Step 5: Write storage tests**

```python
# tests/test_storage.py
import pytest
import tempfile
import os
from server.storage.sqlite import create_sqlite_stores
from server.models import (
    Item, ItemCategory, ItemOrigin, Priority, ItemStatus, ItemFilters, ItemUpdate,
    FilterRule, InteractionEntry, TriageCard, TriageOption, TriageResponse,
    PipelineJob, JobTrigger, JobStatus,
)

@pytest.fixture
async def stores():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        s = await create_sqlite_stores(db_path)
        yield s
    finally:
        os.unlink(db_path)

@pytest.mark.asyncio
async def test_item_crud(stores):
    item = Item(source_type="diff", source_id="D123", summary="test", category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P1)
    saved = await stores.items.save_item(item)
    assert saved.id == item.id

    fetched = await stores.items.get_item(item.id)
    assert fetched.summary == "test"

    updated = await stores.items.update_item(item.id, ItemUpdate(priority=Priority.P0))
    assert updated.priority == Priority.P0

    await stores.items.archive_item(item.id)
    archived = await stores.items.get_item(item.id)
    assert archived.status == ItemStatus.ARCHIVED

@pytest.mark.asyncio
async def test_item_filters(stores):
    await stores.items.save_item(Item(source_type="diff", source_id="D1", summary="a", category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P0))
    await stores.items.save_item(Item(source_type="email", source_id="E1", summary="b", category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.MANUAL, priority=Priority.P3))
    results = await stores.items.get_items(ItemFilters(priority=Priority.P0))
    assert len(results) == 1
    assert results[0].source_id == "D1"

@pytest.mark.asyncio
async def test_filter_rules(stores):
    rule = FilterRule(pattern="CI bot comments", action="drop")
    saved = await stores.filter_rules.add_rule(rule)
    rules = await stores.filter_rules.get_rules()
    assert len(rules) == 1
    assert rules[0].pattern == "CI bot comments"

@pytest.mark.asyncio
async def test_processed_dedup(stores):
    assert not await stores.processed.is_processed("diff", "D123_100")
    await stores.processed.mark_processed("diff", "D123_100")
    assert await stores.processed.is_processed("diff", "D123_100")

@pytest.mark.asyncio
async def test_interaction_log(stores):
    entry = InteractionEntry(source_type="diff", item_summary="test", option_chosen="1")
    await stores.interactions.append(entry)
    assert await stores.interactions.count() == 1
    entries = await stores.interactions.get_all()
    assert entries[0].option_chosen == "1"

@pytest.mark.asyncio
async def test_triage_card_lifecycle(stores):
    card = TriageCard(card_content={"summary": "test"}, options=[TriageOption(label="Skip", action="skip")])
    await stores.triage.save_card(card)
    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    await stores.triage.record_response(card.id, TriageResponse(card_id=card.id, choice=1))
    pending = await stores.triage.get_pending()
    assert len(pending) == 0

@pytest.mark.asyncio
async def test_job_tracking(stores):
    job = PipelineJob(trigger=JobTrigger.MANUAL)
    await stores.jobs.save_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched.status == JobStatus.PENDING
    job.status = JobStatus.COMPLETED
    job.items_extracted = 5
    await stores.jobs.update_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.items_extracted == 5
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_storage.py -v`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
sl commit -m "Add SQLite storage implementation with full test coverage"
```

---

## Task 5: Memory Layer Interface + NoopMemoryLayer

**Files:**
- Create: `server/memory/__init__.py`, `server/memory/base.py`, `server/memory/noop.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write MemoryLayer interface and NoopMemoryLayer**

```python
# server/memory/base.py
from abc import ABC, abstractmethod
from server.models import TriageCard, TriageResponse, Item, Fact, EntityKnowledge, Relationship

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
    async def query_relationships(self, entity_id: str) -> list[Relationship]: ...
    @abstractmethod
    async def is_available(self) -> bool: ...
```

```python
# server/memory/noop.py
from server.memory.base import MemoryLayer
from server.models import TriageCard, TriageResponse, Item, Fact, EntityKnowledge, Relationship

class NoopMemoryLayer(MemoryLayer):
    async def record_triage(self, card, response): pass
    async def record_entity(self, entity_type, entity_id, facts): pass
    async def record_pipeline_decision(self, item, decision, reason): pass
    async def query_preferences(self, context): return []
    async def query_entity(self, entity_type, entity_id): return None
    async def query_relationships(self, entity_id): return []
    async def is_available(self): return False
```

- [ ] **Step 2: Write test**

```python
# tests/test_memory.py
import pytest
from server.memory.noop import NoopMemoryLayer

@pytest.mark.asyncio
async def test_noop_memory_returns_empty():
    memory = NoopMemoryLayer()
    assert await memory.query_preferences("any context") == []
    assert await memory.query_entity("diff", "D123") is None
    assert await memory.query_relationships("D123") == []
    assert await memory.is_available() is False
```

- [ ] **Step 3: Run test and commit**

Run: `python -m pytest tests/test_memory.py -v`

```bash
sl commit -m "Add MemoryLayer interface and NoopMemoryLayer"
```

---

## Task 6: Provider Interfaces

**Files:**
- Create: `server/providers/__init__.py`, `server/providers/llm/base.py`, `server/providers/messenger/base.py`, `server/providers/source/base.py`, `server/providers/doc_reader/base.py`, `server/providers/enrichment/base.py`, `server/providers/enrichment/stub.py`

- [ ] **Step 1: Write all provider ABCs**

```python
# server/providers/llm/base.py
from abc import ABC, abstractmethod
from server.models import ExtractedItem, FilterRule, TriageCard, Fact

class LLMProvider(ABC):
    @abstractmethod
    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]: ...
    @abstractmethod
    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]: ...
    @abstractmethod
    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard: ...
```

```python
# server/providers/messenger/base.py
from abc import ABC, abstractmethod

class Messenger(ABC):
    @abstractmethod
    async def send_card(self, card_text: str) -> str: ...
    @abstractmethod
    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]: ...
```

```python
# server/providers/source/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from server.models import RawItem

class SourceAdapter(ABC):
    @abstractmethod
    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]: ...
    @abstractmethod
    def adapter_type(self) -> str: ...
```

```python
# server/providers/doc_reader/base.py
from abc import ABC, abstractmethod

class DocReader(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool: ...
    @abstractmethod
    async def read(self, url: str) -> str: ...
```

```python
# server/providers/enrichment/base.py
from abc import ABC, abstractmethod
from server.models import ExtractedItem, EnrichmentBudget

class ContextEnricher(ABC):
    @abstractmethod
    async def enrich(self, item: ExtractedItem, depth: str, budget: EnrichmentBudget) -> dict: ...
```

```python
# server/providers/enrichment/stub.py
from server.providers.enrichment.base import ContextEnricher
from server.models import ExtractedItem, EnrichmentBudget

class StubEnricher(ContextEnricher):
    async def enrich(self, item, depth, budget):
        return {"calls_made": 0, "time_ms": 0, "context": {}}
```

- [ ] **Step 2: Commit**

```bash
sl commit -m "Add provider interfaces (LLM, Messenger, Source, DocReader, Enrichment) and StubEnricher"
```

---

## Task 7: Claude LLM Provider

**Files:**
- Create: `server/providers/llm/claude.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: Write ClaudeProvider**

```python
# server/providers/llm/claude.py
import json
import asyncio
from anthropic import AsyncAnthropic
from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact

EXTRACT_PROMPT = """Extract actionable items from the following content. For each item, provide:
- summary: what needs to be done or noted
- category: one of "action_item", "meeting", "informational"
- source_context: relevant surrounding context

Return a JSON array of objects with these fields. Return [] if nothing actionable.

Content type: {source_type}
Content:
{raw_text}"""

SCORE_PROMPT = """Score this item for relevance and confidence (0-100 each).

Item: {summary}
Source: {source_type}

User preferences:
{preferences}

Filter rules:
{rules}

Return JSON: {{"relevance": <0-100>, "confidence": <0-100>}}"""

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str = "claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        self.model = model

    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]:
        raw_item = RawItem(id="", source_type=source_type, source_label="", raw_text=raw_text)
        response = await self._call_with_retry(
            EXTRACT_PROMPT.format(source_type=source_type, raw_text=raw_text[:10000])
        )
        try:
            items_data = json.loads(self._extract_json(response))
            return [
                ExtractedItem(
                    summary=d["summary"],
                    category=ItemCategory(d.get("category", "action_item")),
                    source_context=d.get("source_context", ""),
                    raw_item=raw_item,
                )
                for d in items_data
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]:
        prefs_text = "\n".join(f"- {f.content}" for f in preference_facts) if preference_facts else "No preferences yet."
        rules_text = "\n".join(f"- {r.pattern} → {r.action}" for r in rules) if rules else "No rules yet."
        response = await self._call_with_retry(
            SCORE_PROMPT.format(
                summary=item.summary,
                source_type=item.raw_item.source_type,
                preferences=prefs_text,
                rules=rules_text,
            )
        )
        try:
            scores = json.loads(self._extract_json(response))
            return int(scores["relevance"]), int(scores["confidence"])
        except (json.JSONDecodeError, KeyError):
            return 50, 30  # uncertain defaults

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
        # Template-based options per source type — LLM generates summary only
        summary = item.summary
        options = self._template_options(source_type)
        return TriageCard(
            card_content={"summary": summary, "source_type": source_type, "enrichment": enrichment_context},
            options=options,
        )

    def _template_options(self, source_type: str) -> list[TriageOption]:
        base = [
            TriageOption(label="Add todo (P1)", action="add_todo", details={"priority": "P1"}),
            TriageOption(label="Add todo (P2)", action="add_todo", details={"priority": "P2"}),
            TriageOption(label="Skip", action="skip"),
        ]
        if source_type == "diff":
            base.append(TriageOption(label="Never surface diffs like this", action="mute_pattern"))
        elif source_type == "email":
            base.append(TriageOption(label="Never surface emails like this", action="mute_pattern"))
        else:
            base.append(TriageOption(label="Never surface items like this", action="mute_pattern"))
        return base

    async def _call_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    def _extract_json(self, text: str) -> str:
        # Find JSON in the response (may be wrapped in markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()
```

- [ ] **Step 2: Write test (uses mock to avoid real API calls)**

```python
# tests/test_claude_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from server.providers.llm.claude import ClaudeProvider
from server.models import ExtractedItem, ItemCategory, RawItem, FilterRule, Fact

@pytest.fixture
def provider():
    return ClaudeProvider(api_key="test", base_url="http://test")

@pytest.mark.asyncio
async def test_extract_parses_json_response(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='[{"summary": "Review PR", "category": "action_item", "source_context": "ctx"}]')]
    provider.client = AsyncMock()
    provider.client.messages.create = AsyncMock(return_value=mock_response)

    items = await provider.extract("some text", "diff")
    assert len(items) == 1
    assert items[0].summary == "Review PR"
    assert items[0].category == ItemCategory.ACTION_ITEM

@pytest.mark.asyncio
async def test_score_relevance_parses_scores(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"relevance": 85, "confidence": 90}')]
    provider.client = AsyncMock()
    provider.client.messages.create = AsyncMock(return_value=mock_response)

    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="test")
    item = ExtractedItem(summary="test", category=ItemCategory.ACTION_ITEM, source_context="", raw_item=raw)
    rel, conf = await provider.score_relevance(item, [], [])
    assert rel == 85
    assert conf == 90

@pytest.mark.asyncio
async def test_template_options_vary_by_source(provider):
    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="test")
    item = ExtractedItem(summary="test", category=ItemCategory.ACTION_ITEM, source_context="", raw_item=raw)
    provider.client = AsyncMock()
    card = await provider.generate_triage_card(item, {}, "diff")
    assert any("diff" in o.label.lower() for o in card.options)

    card2 = await provider.generate_triage_card(item, {}, "email")
    assert any("email" in o.label.lower() for o in card2.options)
```

- [ ] **Step 3: Run tests and commit**

Run: `python -m pytest tests/test_claude_provider.py -v`

```bash
sl commit -m "Add ClaudeProvider with extraction, scoring, and triage card generation"
```

---

## Task 8: Pipeline Engine

**Files:**
- Create: `server/pipeline/__init__.py`, `server/pipeline/engine.py`, `server/pipeline/extraction.py`, `server/pipeline/filter.py`, `server/pipeline/enrichment.py`, `server/pipeline/triage.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write pipeline stages**

```python
# server/pipeline/extraction.py
from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem

async def extract_items(llm: LLMProvider, raw_text: str, source_type: str) -> list[ExtractedItem]:
    if not raw_text or len(raw_text.strip()) < 10:
        return []
    return await llm.extract(raw_text, source_type)
```

```python
# server/pipeline/filter.py
from server.providers.llm.base import LLMProvider
from server.memory.base import MemoryLayer
from server.storage.base import FilterRuleStore
from server.models import ExtractedItem

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
    preference_facts = await memory.query_preferences(item.summary)
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

```python
# server/pipeline/enrichment.py
from server.providers.enrichment.base import ContextEnricher
from server.models import ExtractedItem, EnrichmentBudget

async def enrich_item(enricher: ContextEnricher, item: ExtractedItem, depth: str = "shallow", budget: EnrichmentBudget | None = None) -> dict:
    if budget is None:
        budget = EnrichmentBudget()
    return await enricher.enrich(item, depth, budget)
```

```python
# server/pipeline/triage.py
from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem, TriageCard

async def generate_card(llm: LLMProvider, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
    return await llm.generate_triage_card(item, enrichment_context, source_type)

def format_card_for_chat(card: TriageCard, position: int = 1, total: int = 1) -> str:
    """Format a triage card as text for Google Chat."""
    summary = card.card_content.get("summary", "Unknown item")
    source = card.card_content.get("source_type", "unknown")
    lines = []
    if total > 1:
        lines.append(f"*{total} items to triage. Here's #{position} of {total}:*")
    lines.append(f"*[{source}]* {summary}")
    enrichment = card.card_content.get("enrichment", {})
    if enrichment:
        ctx = enrichment.get("context", {})
        if ctx:
            lines.append(f"_Context: {', '.join(str(v) for v in ctx.values())}_")
    lines.append("")
    lines.append("*What do you want to do?*")
    for i, opt in enumerate(card.options, 1):
        lines.append(f"{i}. {opt.label}")
    return "\n".join(lines)
```

- [ ] **Step 2: Write pipeline engine**

```python
# server/pipeline/engine.py
import hashlib
import logging
from datetime import datetime
from server.storage.base import Stores
from server.memory.base import MemoryLayer
from server.providers.llm.base import LLMProvider
from server.providers.enrichment.base import ContextEnricher
from server.pipeline.extraction import extract_items
from server.pipeline.filter import score_and_decide
from server.pipeline.enrichment import enrich_item
from server.pipeline.triage import generate_card
from server.models import (
    RawItem, Item, ItemCategory, ItemOrigin, Priority,
    PipelineJob, JobTrigger, JobStatus, InteractionEntry,
)

logger = logging.getLogger(__name__)

class PipelineEngine:
    def __init__(self, stores: Stores, memory: MemoryLayer, llm: LLMProvider, enricher: ContextEnricher):
        self.stores = stores
        self.memory = memory
        self.llm = llm
        self.enricher = enricher

    async def process(self, raw_text: str, source_type: str, trigger: JobTrigger = JobTrigger.MANUAL) -> PipelineJob:
        job = PipelineJob(trigger=trigger, input_hash=hashlib.sha256(raw_text.encode()).hexdigest())
        await self.stores.jobs.save_job(job)
        job.status = JobStatus.RUNNING
        await self.stores.jobs.update_job(job)

        try:
            extracted = await extract_items(self.llm, raw_text, source_type)
            job.items_extracted = len(extracted)

            for ext_item in extracted:
                try:
                    await self._process_extracted_item(ext_item, job)
                except Exception as e:
                    logger.error(f"Failed to process item: {e}")
                    job.items_failed += 1

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()

        await self.stores.jobs.update_job(job)
        return job

    async def _process_extracted_item(self, ext_item, job: PipelineJob):
        action, relevance, confidence = await score_and_decide(
            self.llm, self.memory, self.stores.filter_rules, ext_item
        )

        if action == "auto_include":
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary,
                category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED,
                priority=Priority.P2,
            )
            await self.stores.items.save_item(item)
            await self.memory.record_pipeline_decision(item, "auto_include", f"relevance={relevance}")
            job.items_included += 1

        elif action == "auto_drop":
            await self.memory.record_pipeline_decision(
                Item(source_type=ext_item.raw_item.source_type, source_id=ext_item.raw_item.id,
                     summary=ext_item.summary, category=ext_item.category,
                     origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P3),
                "auto_drop", f"relevance={relevance}"
            )
            job.items_dropped += 1

        else:  # triage
            enrichment = await enrich_item(self.enricher, ext_item)
            card = await generate_card(self.llm, ext_item, enrichment, ext_item.raw_item.source_type)
            await self.stores.triage.save_card(card)
            job.items_triaged += 1
```

- [ ] **Step 3: Write pipeline tests**

```python
# tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock
from server.pipeline.engine import PipelineEngine
from server.pipeline.filter import score_and_decide
from server.pipeline.triage import format_card_for_chat
from server.memory.noop import NoopMemoryLayer
from server.providers.enrichment.stub import StubEnricher
from server.models import (
    ExtractedItem, ItemCategory, RawItem, TriageCard, TriageOption,
    FilterRule, JobTrigger, JobStatus,
)
import tempfile, os
from server.storage.sqlite import create_sqlite_stores

@pytest.fixture
async def stores():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield await create_sqlite_stores(db_path)
    finally:
        os.unlink(db_path)

@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.extract.return_value = [
        ExtractedItem(
            summary="Review auth PR",
            category=ItemCategory.ACTION_ITEM,
            source_context="ctx",
            raw_item=RawItem(id="D123_100", source_type="diff", source_label="D123", raw_text="test"),
        )
    ]
    llm.score_relevance.return_value = (85, 90)
    llm.generate_triage_card.return_value = TriageCard(
        card_content={"summary": "Review auth PR", "source_type": "diff"},
        options=[TriageOption(label="Add todo (P1)", action="add_todo")],
    )
    return llm

@pytest.mark.asyncio
async def test_pipeline_auto_include(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("diff content", "diff")
    assert job.status == JobStatus.COMPLETED
    assert job.items_extracted == 1
    assert job.items_included == 1
    items = await stores.items.get_items(stores.items.__class__.__bases__[0].__subclasses__()[0].__init__.__annotations__.get("filters", None) or __import__("server.models", fromlist=["ItemFilters"]).ItemFilters())
    # Simpler check:
    from server.models import ItemFilters
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1

@pytest.mark.asyncio
async def test_pipeline_auto_drop(stores, mock_llm):
    mock_llm.score_relevance.return_value = (10, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("spam content", "email")
    assert job.items_dropped == 1
    from server.models import ItemFilters
    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 0

@pytest.mark.asyncio
async def test_pipeline_triage(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.process("ambiguous content", "email")
    assert job.items_triaged == 1
    pending = await stores.triage.get_pending()
    assert len(pending) == 1

def test_format_card_for_chat():
    card = TriageCard(
        card_content={"summary": "Review D123", "source_type": "diff"},
        options=[
            TriageOption(label="Add todo (P1)", action="add_todo"),
            TriageOption(label="Skip", action="skip"),
        ],
    )
    text = format_card_for_chat(card, position=1, total=3)
    assert "3 items to triage" in text
    assert "Review D123" in text
    assert "1. Add todo (P1)" in text
    assert "2. Skip" in text
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_pipeline.py -v`

```bash
sl commit -m "Add pipeline engine with extraction, filtering, enrichment, and triage card generation"
```

---

## Task 9: API Endpoints

**Files:**
- Create: `server/api/__init__.py`, `server/api/health.py`, `server/api/items.py`, `server/api/triage.py`, `server/api/process.py`, `server/api/filter_rules.py`, `server/api/sources.py`, `server/api/config.py`, `server/api/memory.py`, `server/api/jobs.py`
- Modify: `server/main.py` — mount routers, wire up stores and pipeline
- Test: `tests/test_api.py`

- [ ] **Step 1: Write API routers**

Each router is a FastAPI `APIRouter` that receives `stores` and `pipeline` via app state. Example for items:

```python
# server/api/items.py
from fastapi import APIRouter, HTTPException
from server.models import ItemFilters, ItemUpdate

router = APIRouter(prefix="/api", tags=["items"])

@router.get("/items")
async def list_items(priority: str = None, status: str = None, source_type: str = None):
    stores = router.app.state.stores
    filters = ItemFilters(priority=priority, status=status, source_type=source_type)
    return await stores.items.get_items(filters)

@router.patch("/items/{item_id}")
async def update_item(item_id: str, updates: ItemUpdate):
    stores = router.app.state.stores
    item = await stores.items.get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return await stores.items.update_item(item_id, updates)

@router.delete("/items/{item_id}")
async def archive_item(item_id: str):
    stores = router.app.state.stores
    await stores.items.archive_item(item_id)
    return {"status": "archived"}
```

Write similar routers for: `triage.py` (GET pending, POST respond), `process.py` (POST /api/process), `filter_rules.py` (GET/POST), `sources.py` (CRUD), `config.py` (GET/PATCH), `memory.py` (GET /api/memory/facts — returns empty list for Phase 1a), `jobs.py` (GET /api/jobs/{job_id}).

- [ ] **Step 2: Wire up main.py with stores and pipeline**

```python
# server/main.py (updated)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from server.config import Settings
from server.auth import BearerTokenMiddleware
from server.storage.factory import create_stores
from server.memory.noop import NoopMemoryLayer
from server.providers.llm.claude import ClaudeProvider
from server.providers.enrichment.stub import StubEnricher
from server.pipeline.engine import PipelineEngine
from server.api import items, triage, process, filter_rules, sources, config, memory, jobs

settings = Settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.stores = await create_stores(settings)
    app.state.memory = NoopMemoryLayer()
    app.state.llm = ClaudeProvider(settings.anthropic_api_key, settings.anthropic_base_url)
    app.state.enricher = StubEnricher()
    app.state.pipeline = PipelineEngine(app.state.stores, app.state.memory, app.state.llm, app.state.enricher)
    yield

app = FastAPI(title="Workbench", version="0.1.0", lifespan=lifespan)
app.add_middleware(BearerTokenMiddleware, token=settings.api_token)

@app.get("/health")
async def health():
    return {"status": "ok"}

for r in [items.router, triage.router, process.router, filter_rules.router, sources.router, config.router, memory.router, jobs.router]:
    app.include_router(r)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
```

- [ ] **Step 3: Write API tests**

```python
# tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from server.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": "Bearer dev-token-change-me"}) as c:
        yield c

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_health_no_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200

@pytest.mark.asyncio
async def test_items_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/items")
        assert r.status_code == 401

@pytest.mark.asyncio
async def test_items_empty(client):
    r = await client.get("/api/items")
    assert r.status_code == 200
    assert r.json() == []

@pytest.mark.asyncio
async def test_filter_rules_crud(client):
    r = await client.post("/api/filter-rules", json={"pattern": "CI bot comments", "action": "drop"})
    assert r.status_code == 200
    r = await client.get("/api/filter-rules")
    assert len(r.json()) == 1
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_api.py -v`

```bash
sl commit -m "Add REST API endpoints and wire up FastAPI with stores and pipeline"
```

---

## Task 10: Google Chat Messenger

**Files:**
- Create: `server/providers/messenger/google_chat.py`
- Test: `tests/test_google_chat.py`

- [ ] **Step 1: Write GoogleChatMessenger**

Wraps `google_api.py` calls via subprocess (same approach the existing script uses):

```python
# server/providers/messenger/google_chat.py
import json
import subprocess
from server.providers.messenger.base import Messenger

class GoogleChatMessenger(Messenger):
    def __init__(self, space_id: str, google_api_script: str):
        self.space_id = space_id
        self.script = google_api_script

    async def send_card(self, card_text: str) -> str:
        result = self._run({"action": "send_message", "space_id": self.space_id, "text": card_text, "as_bot": True})
        if result.get("success"):
            return result["data"].get("name", "")
        raise RuntimeError(f"Failed to send message: {result.get('error', 'unknown')}")

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        result = self._run({"action": "list_messages", "space_id": self.space_id})
        if not result.get("success"):
            return []
        messages = result["data"].get("messages", [])
        human_msgs = [m for m in messages if m.get("sender_type") == "HUMAN"]
        if since_message_id:
            # Return only messages after the given message
            found = False
            filtered = []
            for m in human_msgs:
                if found:
                    filtered.append(m)
                if m.get("name") == since_message_id:
                    found = True
            return filtered
        return human_msgs

    def _run(self, params: dict) -> dict:
        result = subprocess.run(
            ["python3", self.script, json.dumps(params)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
```

- [ ] **Step 2: Write test (mocked subprocess)**

```python
# tests/test_google_chat.py
import pytest
import json
from unittest.mock import patch, MagicMock
from server.providers.messenger.google_chat import GoogleChatMessenger

@pytest.fixture
def messenger():
    return GoogleChatMessenger(space_id="AAQA-RI-cA4", google_api_script="/fake/script.py")

@pytest.mark.asyncio
async def test_send_card(messenger):
    mock_result = MagicMock(returncode=0, stdout=json.dumps({"success": True, "data": {"name": "spaces/X/messages/Y"}}))
    with patch("subprocess.run", return_value=mock_result):
        msg_id = await messenger.send_card("test message")
        assert msg_id == "spaces/X/messages/Y"

@pytest.mark.asyncio
async def test_poll_responses_filters_human(messenger):
    messages = [
        {"name": "msg1", "sender_type": "BOT", "text": "card"},
        {"name": "msg2", "sender_type": "HUMAN", "text": "1"},
    ]
    mock_result = MagicMock(returncode=0, stdout=json.dumps({"success": True, "data": {"messages": messages}}))
    with patch("subprocess.run", return_value=mock_result):
        responses = await messenger.poll_responses()
        assert len(responses) == 1
        assert responses[0]["text"] == "1"
```

- [ ] **Step 3: Run tests and commit**

Run: `python -m pytest tests/test_google_chat.py -v`

```bash
sl commit -m "Add GoogleChatMessenger wrapping google_api.py"
```

---

## Task 11: Scheduler + Triage Queue

**Files:**
- Create: `server/pipeline/scheduler.py`
- Modify: `server/main.py` — start scheduler on startup

- [ ] **Step 1: Write scheduler with triage queue manager**

```python
# server/pipeline/scheduler.py
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from server.storage.base import Stores
from server.memory.base import MemoryLayer
from server.pipeline.engine import PipelineEngine
from server.pipeline.triage import format_card_for_chat
from server.providers.messenger.base import Messenger
from server.models import TriageResponse, InteractionEntry, FilterRule, ItemOrigin, ItemCategory, Priority, Item

logger = logging.getLogger(__name__)

class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine, messenger: Messenger | None, settings):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.settings = settings
        self.scheduler = AsyncIOScheduler()
        self._last_bot_message_id: str | None = None

    def start(self):
        self.scheduler.add_job(self._poll_sources, "interval", minutes=self.settings.poll_interval_minutes, id="poll")
        self.scheduler.add_job(self._manage_triage_queue, "interval", seconds=30, id="triage_queue")
        self.scheduler.add_job(self._morning_briefing, "cron", hour=self.settings.morning_briefing_hour, id="briefing")
        self.scheduler.start()

    async def _poll_sources(self):
        sources = await self.stores.sources.get_sources()
        for source in sources:
            if not source.enabled:
                continue
            logger.info(f"Polling {source.adapter_type}")
            # Source polling will be implemented when source adapters are wired up

    async def _manage_triage_queue(self):
        if not self.messenger:
            return
        pending = await self.stores.triage.get_pending()
        if not pending:
            return

        # Send the first unsent card
        card = pending[0]
        if card.sent_at is None:
            text = format_card_for_chat(card, position=1, total=len(pending))
            msg_id = await self.messenger.send_card(text)
            card.sent_at = datetime.utcnow()
            await self.stores.triage.save_card(card)
            self._last_bot_message_id = msg_id
            return

        # Poll for response to the current card
        responses = await self.messenger.poll_responses(self._last_bot_message_id)
        for resp in responses:
            text = resp.get("text", "").strip().lower()
            if text == "skip all" or text == "skip remaining":
                # Mark all pending as skipped
                for c in pending:
                    if c.responded_at is None:
                        await self.stores.triage.record_response(c.id, TriageResponse(card_id=c.id, choice=0, raw_text="skip all"))
                return

            try:
                choice = int(text)
                if 1 <= choice <= len(card.options):
                    await self._handle_triage_response(card, choice)
                    return
            except ValueError:
                pass

    async def _handle_triage_response(self, card, choice: int):
        option = card.options[choice - 1]
        response = TriageResponse(card_id=card.id, choice=choice)
        await self.stores.triage.record_response(card.id, response)

        if option.action == "add_todo":
            priority = Priority(option.details.get("priority", "P2"))
            item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=card.card_content.get("summary", ""),
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=priority,
            )
            await self.stores.items.save_item(item)

        elif option.action == "mute_pattern":
            rule = FilterRule(
                source_type=card.card_content.get("source_type"),
                pattern=card.card_content.get("summary", ""),
                action="drop",
                created_from_interaction_id=card.id,
            )
            await self.stores.filter_rules.add_rule(rule)

        # Log interaction
        entry = InteractionEntry(
            source_type=card.card_content.get("source_type", "unknown"),
            item_summary=card.card_content.get("summary", ""),
            triage_card_full=card.card_content,
            options_presented=[o.model_dump() for o in card.options],
            option_chosen=option.label,
        )
        await self.stores.interactions.append(entry)
        await self.memory.record_triage(card, response)

    async def _morning_briefing(self):
        if not self.messenger:
            return
        from server.models import ItemFilters, ItemStatus
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]
        if p0:
            lines.append(f"*P0 — Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  - {i.summary} [{i.source_type}]")
        if p1:
            lines.append(f"*P1 — This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  - {i.summary} [{i.source_type}]")
        if pending:
            lines.append(f"\n_{len(pending)} items pending triage_")
        if not p0 and not p1 and not pending:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
```

- [ ] **Step 2: Wire scheduler into main.py startup**

Add to the `lifespan` context manager in `server/main.py`:

```python
from server.pipeline.scheduler import WorkbenchScheduler
from server.providers.messenger.google_chat import GoogleChatMessenger

# Inside lifespan, after pipeline setup:
messenger = None
if settings.gchat_space_id:
    messenger = GoogleChatMessenger(settings.gchat_space_id, settings.google_api_script)

app.state.scheduler = WorkbenchScheduler(app.state.stores, app.state.memory, app.state.pipeline, messenger, settings)
app.state.scheduler.start()
```

- [ ] **Step 3: Commit**

```bash
sl commit -m "Add scheduler with triage queue manager and morning briefing"
```

---

## Task 12: Source Adapters (Phabricator + Gmail)

**Files:**
- Create: `server/providers/source/phabricator.py`, `server/providers/source/email_gmail.py`

These will be implemented with stubs initially, then wired to real APIs. The full Conduit/Gmail API integration requires testing against real services and will be refined during end-to-end testing.

- [ ] **Step 1: Write PhabricatorAdapter skeleton**

```python
# server/providers/source/phabricator.py
import subprocess
import json
from datetime import datetime
from server.providers.source.base import SourceAdapter
from server.models import RawItem

class PhabricatorAdapter(SourceAdapter):
    def adapter_type(self) -> str:
        return "diff"

    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        user_phid = config.get("user_phid", "")
        if not user_phid:
            return []

        items = []
        # Fetch diffs authored by user
        items.extend(await self._query_diffs({"authorPHIDs": [user_phid]}, since))
        # Fetch diffs where user is reviewer
        items.extend(await self._query_diffs({"reviewerPHIDs": [user_phid]}, since))
        return items

    async def _query_diffs(self, constraints: dict, since: datetime | None) -> list[RawItem]:
        if since:
            constraints["modifiedStart"] = int(since.timestamp())
        params = {"constraints": constraints, "limit": 50}
        result = self._conduit_call("differential.revision.search", params)
        if not result:
            return []
        items = []
        for rev in result.get("data", []):
            rev_id = rev["id"]
            mod_time = rev["fields"].get("dateModified", 0)
            items.append(RawItem(
                id=f"D{rev_id}_{mod_time}",
                source_type="diff",
                source_label=f"D{rev_id} — {rev['fields'].get('title', '')}",
                raw_text=json.dumps(rev["fields"]),
            ))
        return items

    def _conduit_call(self, method: str, params: dict) -> dict | None:
        try:
            result = subprocess.run(
                ["arc", "call-conduit", method],
                input=json.dumps(params),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout).get("response", {})
        except Exception:
            return None
```

- [ ] **Step 2: Write GmailAdapter skeleton**

```python
# server/providers/source/email_gmail.py
import json
import subprocess
from datetime import datetime
from server.providers.source.base import SourceAdapter
from server.models import RawItem

class GmailAdapter(SourceAdapter):
    def adapter_type(self) -> str:
        return "email"

    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        google_api_script = config.get("google_api_script", "")
        if not google_api_script:
            return []
        # Gmail polling via Google API proxy — to be refined during e2e testing
        # For now, returns empty list
        return []
```

- [ ] **Step 3: Commit**

```bash
sl commit -m "Add Phabricator and Gmail source adapter skeletons"
```

---

## Task 13: MCP Server

**Files:**
- Create: `server/mcp/__init__.py`, `server/mcp/server.py`, `server/mcp/tools.py`

- [ ] **Step 1: Write MCP tool definitions**

The MCP server exposes the same operations as the REST API. Implementation wraps the same stores and pipeline. This task creates the tool definitions — wiring to a transport (stdio or SSE) is a follow-up.

```python
# server/mcp/tools.py
from server.storage.base import Stores
from server.pipeline.engine import PipelineEngine
from server.models import ItemFilters, JobTrigger

class WorkbenchMCPTools:
    def __init__(self, stores: Stores, pipeline: PipelineEngine):
        self.stores = stores
        self.pipeline = pipeline

    async def workbench_process(self, text: str, source_type: str = "manual") -> dict:
        job = await self.pipeline.process(text, source_type, JobTrigger.MANUAL)
        return {"job_id": job.id, "status": job.status.value}

    async def workbench_items(self, priority: str = None, status: str = None) -> list[dict]:
        items = await self.stores.items.get_items(ItemFilters(priority=priority, status=status))
        return [i.model_dump() for i in items]

    async def workbench_triage_pending(self) -> list[dict]:
        cards = await self.stores.triage.get_pending()
        return [c.model_dump() for c in cards]

    async def workbench_status(self) -> dict:
        items = await self.stores.items.get_items(ItemFilters())
        pending = await self.stores.triage.get_pending()
        return {
            "total_items": len(items),
            "pending_triage": len(pending),
            "active_items": len([i for i in items if i.status.value == "active"]),
        }
```

- [ ] **Step 2: Commit**

```bash
sl commit -m "Add MCP tool definitions"
```

---

## Task 14: Claude Code Plugin

**Files:**
- Create: `plugin/.claude-plugin/plugin.json`, `plugin/commands/process.md`, `plugin/commands/setup.md`, `plugin/commands/status.md`, `plugin/commands/triage.md`, `plugin/commands/sources.md`, `plugin/config/config.json`

- [ ] **Step 1: Write plugin manifest**

```json
// plugin/.claude-plugin/plugin.json
{
  "name": "workbench",
  "version": "0.1.0",
  "description": "Workbench Intelligence Feed — triage, status, and processing commands"
}
```

- [ ] **Step 2: Write plugin commands**

Each command is a markdown file that instructs Claude Code to make HTTP calls to the server.

```markdown
<!-- plugin/commands/status.md -->
# /workbench:status

Show the Workbench dashboard — active items by priority, pending triage count, and system health.

## Instructions

1. Read the server URL from `plugin/config/config.json` (default: `http://devgpu004.lla1.facebook.com:8421`)
2. Read the API token from the same config file
3. Call `GET {server_url}/health` with `Authorization: Bearer {token}` — verify the server is running
4. Call `GET {server_url}/api/items?status=active` with the same auth header
5. Call `GET {server_url}/api/triage/pending` with the same auth header
6. Format the response as a dashboard:
   - Group items by priority (P0, P1, P2, P3)
   - Show pending triage count
   - Show server health status
```

Write similar commands for `process.md`, `setup.md`, `triage.md`, `sources.md`. Each follows the same pattern: read config, make HTTP calls, format response.

- [ ] **Step 3: Write config**

```json
// plugin/config/config.json
{
  "server_url": "http://devgpu004.lla1.facebook.com:8421",
  "api_token": "dev-token-change-me"
}
```

- [ ] **Step 4: Commit**

```bash
sl commit -m "Add Claude Code plugin with slash commands"
```

---

## Task 15: End-to-End Verification

- [ ] **Step 1: Build and start the stack**

```bash
podman compose build
podman compose up -d
```

- [ ] **Step 2: Verify health**

```bash
curl http://localhost:8421/health
# Expected: {"status":"ok"}
```

- [ ] **Step 3: Test manual processing**

```bash
curl -X POST http://localhost:8421/api/process \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"text": "Meeting with Alice: discussed auth migration. Action items: 1) Write design doc by Friday 2) Set up test environment", "source_type": "meeting"}'
```
Expected: Returns `{job_id, status: "pending"}`. Check Google Chat for a triage card (if `GCHAT_SPACE_ID` is set).

- [ ] **Step 4: Test triage response**

In Google Chat, reply with "1" to the triage card. Check:
```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/items
```
Expected: The item appears with the selected priority.

- [ ] **Step 5: Test filter rule creation**

Reply with "4" (mute pattern) to a triage card. Check:
```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/filter-rules
```
Expected: A new filter rule appears.

- [ ] **Step 6: Commit final state**

```bash
sl commit -m "End-to-end verification complete: core triage loop working"
```

---

## What's Next

After Phase 1a is working end-to-end, the following phases add intelligence:

- **Phase 1b**: Stand up Zep via Podman, implement `ZepMemoryLayer`, wire preferences
- **Phase 1c**: Wire entity knowledge into enrichment
- **Phase 1d**: Wire relationship context into triage card generation
- **Phase 2**: XDB storage backend, additional source adapters (Tasks, Workplace, Calendar, SEVs, Oncall)
