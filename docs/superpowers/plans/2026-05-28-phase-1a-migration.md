# Phase 1a: Core Triage Loop — Migration & Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the working Phase 1a server from `server/` (SQLite, pydantic-settings) to `src/workbench/` (PostgreSQL, YAML/OmegaConf config, provider registry, durable ingestion queue with LLM scoring). End state: a fully operational triage loop running in Podman on a devgpu.

**Architecture:** FastAPI server in `src/workbench/` package. PostgreSQL (single instance, two databases: `workbench` + `zep`) for all persistence. YAML config with OmegaConf env var interpolation. Provider registry with dynamic import and typed `ProviderConfig` validation. Durable ingestion queue with LLM-based priority scoring (Haiku) and async worker. Triage queue persisted as columns on `triage_cards` with relevance-score ordering. Claude API via Plugboard for LLM. Google Chat for triage cards. NoopMemoryLayer (Zep deferred to Phase 1b).

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Alembic, OmegaConf, Anthropic Python SDK, Pydantic v2, APScheduler, Podman Compose

**Existing code:** The `server/` directory contains a working Phase 1a implementation tested against real services (Plugboard LLM, Google Chat). This plan migrates it to the new architecture defined in ADRs 0006-0008 and the internal/external split design spec.

**Specs:**
- `docs/specs/2026-05-21-workbench-design.md` — main design spec
- `docs/specs/2026-05-27-zep-memory-layer-design.md` — Zep spec (Phase 1b)
- `docs/superpowers/specs/2026-05-27-internal-external-split-design.md` — config/registry/provider system
- `docs/adr/0006-postgres-over-sqlite.md` — PostgreSQL as primary storage
- `docs/adr/0007-durable-queues-with-llm-scoring.md` — ingestion queue + QueueScorer
- `docs/adr/0008-src-layout-and-versioning.md` — `src/workbench/` layout
- `CONTEXT.md` — domain glossary (authoritative term definitions)

---

## File Structure

```
workbench/                              # repo root
├── pyproject.toml                      # package metadata, dependencies, entry points
├── Dockerfile                          # builds from src/ layout
├── docker-compose.yml                  # workbench + postgres (single instance)
├── config.example.yml                  # template config (committed)
├── init-db.sh                          # creates workbench + zep databases
├── alembic.ini                         # Alembic config (points to src/workbench/migrations)
├── CONTEXT.md
├── CLAUDE.md
├── .gitignore
├── src/
│   └── workbench/
│       ├── __init__.py                 # __version__ = "0.1.0"
│       ├── main.py                     # FastAPI app, lifespan, registry wiring
│       ├── config.py                   # YAML loader, AppConfig, section configs
│       ├── registry.py                 # provider discovery + factory
│       ├── auth.py                     # bearer token middleware
│       ├── models.py                   # all Pydantic domain models
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── base.py                 # all repository ABCs + Stores bundle
│       │   ├── factory.py              # create_stores() → PG
│       │   └── postgres/
│       │       ├── __init__.py         # create_postgres_stores()
│       │       ├── pool.py             # asyncpg connection pool management
│       │       ├── items.py            # PgItemStore
│       │       ├── triage.py           # PgTriageStore (with queue columns)
│       │       ├── plans.py            # PgPlanStore
│       │       ├── interactions.py     # PgInteractionStore
│       │       ├── filter_rules.py     # PgFilterRuleStore
│       │       ├── enrichment.py       # PgEnrichmentTraceStore
│       │       ├── sources.py          # PgSourceConfigStore
│       │       ├── processed.py        # PgProcessedStore
│       │       ├── config.py           # PgConfigStore
│       │       ├── jobs.py             # PgJobStore
│       │       └── ingestion_queue.py  # PgIngestionQueueStore
│       ├── migrations/
│       │   ├── env.py                  # Alembic env (asyncpg)
│       │   ├── script.py.mako          # migration template
│       │   └── versions/
│       │       └── 001_initial_schema.py
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── base.py                 # MemoryLayer ABC
│       │   └── noop.py                 # NoopMemoryLayer
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── llm/
│       │   │   ├── __init__.py
│       │   │   ├── base.py             # LLMProvider ABC
│       │   │   └── claude.py           # ClaudeProvider (Plugboard + x509)
│       │   ├── messenger/
│       │   │   ├── __init__.py
│       │   │   ├── base.py             # Messenger ABC
│       │   │   └── google_chat.py      # GoogleChatMessenger (async subprocess)
│       │   ├── source/
│       │   │   ├── __init__.py
│       │   │   ├── base.py             # SourceAdapter ABC
│       │   │   ├── phabricator.py      # PhabricatorAdapter (async subprocess)
│       │   │   └── email_gmail.py      # GmailAdapter
│       │   ├── doc_reader/
│       │   │   ├── __init__.py
│       │   │   └── base.py             # DocReader ABC
│       │   ├── enrichment/
│       │   │   ├── __init__.py
│       │   │   ├── base.py             # ContextEnricher ABC
│       │   │   └── stub.py             # StubEnricher
│       │   └── queue_scorer/
│       │       ├── __init__.py
│       │       ├── base.py             # QueueScorer ABC
│       │       └── llm.py              # LLMQueueScorer (Haiku)
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── engine.py               # PipelineEngine (processes dequeued items)
│       │   ├── extraction.py           # extract_items()
│       │   ├── filter.py               # score_and_decide()
│       │   ├── enrichment.py           # enrich_item()
│       │   ├── triage.py               # generate_card(), format_card_for_chat()
│       │   ├── scheduler.py            # WorkbenchScheduler
│       │   └── worker.py               # IngestionQueueWorker (async, semaphore)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── health.py               # GET /health (version, PG check, queue stats)
│       │   ├── items.py
│       │   ├── triage.py
│       │   ├── process.py              # POST /api/process (enqueues, returns job)
│       │   ├── filter_rules.py
│       │   ├── sources.py              # GET + PATCH only (no POST/DELETE)
│       │   ├── config.py
│       │   ├── memory.py
│       │   ├── jobs.py
│       │   └── queue.py                # dead-letter endpoints
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── tools.py
│       └── lib/
│           └── google_api.py           # standalone GChat API script
├── plugin/                             # (exists, minor config update)
│   ├── .claude-plugin/plugin.json
│   ├── commands/
│   └── config/
│       └── config.json
├── tests/
│   ├── conftest.py                     # PG fixtures, test config
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_registry.py
│   ├── test_storage.py
│   ├── test_pipeline.py
│   ├── test_api.py
│   ├── test_queue_worker.py
│   ├── test_queue_scorer.py
│   └── test_filter.py
└── docs/                               # (exists)
```

---

## Task 1: Package Rename + Build System

**Goal:** Move `server/` to `src/workbench/`, update every import, create `pyproject.toml`. After this task, `python -c "from workbench.models import Item"` works.

**Files:**
- Move: `server/` → `src/workbench/` (all files)
- Create: `pyproject.toml`, `src/workbench/__init__.py`
- Modify: every `.py` file (imports `server.X` → `workbench.X`)
- Delete: `server/requirements.txt` (replaced by pyproject.toml)

- [ ] **Step 1: Create directory structure and move files**

```bash
mkdir -p src
mv server src/workbench
```

- [ ] **Step 2: Create `src/workbench/__init__.py`**

```python
# src/workbench/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "workbench"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "anthropic>=0.40",
    "apscheduler>=3.10",
    "httpx>=0.27",
    "omegaconf>=2.3",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
]

[project.scripts]
workbench = "workbench.main:cli_main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: Update all imports from `server.X` to `workbench.X`**

Run this sed command across all Python files:

```bash
find src/workbench tests -name '*.py' -exec sed -i 's/from server\./from workbench./g; s/import server\./import workbench./g' {} +
```

Verify no `server.` imports remain:

```bash
grep -rn 'from server\.\|import server\.' src/ tests/
```

Expected: zero results.

- [ ] **Step 5: Update Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .
EXPOSE 8421
CMD ["alembic", "upgrade", "head", "&&", "uvicorn", "workbench.main:app", "--host", "0.0.0.0", "--port", "8421"]
```

Note: The CMD will be refined in Task 3 (Docker Stack) with a proper entrypoint script.

- [ ] **Step 6: Delete old requirements.txt**

```bash
rm -f src/workbench/requirements.txt
```

- [ ] **Step 7: Install in dev mode and verify imports**

```bash
pip install -e ".[dev]"
python -c "from workbench.models import Item, Priority; print('OK')"
python -c "from workbench import __version__; print(__version__)"
```

Expected: `OK` and `0.1.0`.

- [ ] **Step 8: Run existing tests to verify nothing broke**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | head -50
```

Expected: Tests that don't depend on a running database should still pass (test_models.py, test_memory.py, test_claude_provider.py, test_google_chat.py). Storage and API tests may fail due to import changes — that's OK, they'll be rewritten.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "Rename server/ to src/workbench/ with src layout (ADR 0008)"
```

---

## Task 2: Domain Models Update

**Goal:** Update `models.py` to match CONTEXT.md and ADR 0007. Add `PENDING_TRIAGE` item status, `QUEUED` job status, `PLAN_SEED` category, `urgency_signals` on `RawItem`, and queue-related models.

**Files:**
- Modify: `src/workbench/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Add missing enum values and fields**

In `src/workbench/models.py`:

Add `PENDING_TRIAGE` to `ItemStatus`:

```python
class ItemStatus(str, Enum):
    PENDING_TRIAGE = "pending_triage"
    ACTIVE = "active"
    DONE = "done"
    ARCHIVED = "archived"
```

Add `QUEUED` to `JobStatus`:

```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

Add `PLAN_SEED` to `ItemCategory`:

```python
class ItemCategory(str, Enum):
    ACTION_ITEM = "action_item"
    MEETING = "meeting"
    PLAN_SEED = "plan_seed"
    INFORMATIONAL = "informational"
```

Add `urgency_signals` to `RawItem`:

```python
class RawItem(BaseModel):
    id: str
    source_type: str
    source_label: str
    raw_text: str
    urgency_signals: dict[str, Any] = Field(default_factory=dict)
```

Add `from typing import Any` to the imports at the top of the file.

- [ ] **Step 2: Add ingestion queue models**

Append to `src/workbench/models.py`:

```python
class QueueEntryStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

class IngestionQueueEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_content: str
    source_type: str
    source_id: str | None = None
    urgency_signals: dict[str, Any] = Field(default_factory=dict)
    urgency_score: int = 50
    job_id: str
    status: QueueEntryStatus = QueueEntryStatus.QUEUED
    attempt: int = 0
    max_attempts: int = 3
    next_retry_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 3: Add triage queue fields to TriageCard**

Update the `TriageCard` model:

```python
class TriageCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_id: str | None = None
    card_content: dict = Field(default_factory=dict)
    options: list[TriageOption] = Field(default_factory=list)
    relevance_score: int = 50
    confidence_score: int = 50
    status: str = "queued"  # queued, sent, responded, expired
    bot_message_id: str | None = None
    daily_sequence: int | None = None
    expires_at: datetime | None = None
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    response: str | None = None
```

- [ ] **Step 4: Update Item default status**

Change `Item.status` default to `PENDING_TRIAGE` for items created by triage:

```python
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
```

Note: `status` default stays `ACTIVE` — the pipeline explicitly sets `PENDING_TRIAGE` when creating items for triage and `ACTIVE` for auto-included items.

- [ ] **Step 5: Write tests for new models**

Add to `tests/test_models.py`:

```python
from workbench.models import (
    IngestionQueueEntry, QueueEntryStatus,
    ItemStatus, JobStatus, ItemCategory,
    RawItem, TriageCard,
)

def test_item_status_includes_pending_triage():
    assert ItemStatus.PENDING_TRIAGE.value == "pending_triage"

def test_job_status_includes_queued():
    assert JobStatus.QUEUED.value == "queued"

def test_item_category_includes_plan_seed():
    assert ItemCategory.PLAN_SEED.value == "plan_seed"

def test_raw_item_has_urgency_signals():
    raw = RawItem(id="1", source_type="diff", source_label="D123", raw_text="content")
    assert raw.urgency_signals == {}
    raw2 = RawItem(id="2", source_type="diff", source_label="D456", raw_text="content",
                   urgency_signals={"blocking_reviewer": True})
    assert raw2.urgency_signals["blocking_reviewer"] is True

def test_ingestion_queue_entry_defaults():
    entry = IngestionQueueEntry(raw_content="test", source_type="manual", job_id="j1")
    assert entry.status == QueueEntryStatus.QUEUED
    assert entry.attempt == 0
    assert entry.urgency_score == 50

def test_triage_card_queue_fields():
    card = TriageCard()
    assert card.status == "queued"
    assert card.relevance_score == 50
    assert card.bot_message_id is None
    assert card.expires_at is None
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_models.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/models.py tests/test_models.py && git commit -m "Update domain models: pending_triage, queued status, urgency_signals, queue models (ADR 0007)"
```

---

## Task 3: Docker Stack

**Goal:** Set up the Podman Compose stack with a single PostgreSQL instance hosting two databases (`workbench` + `zep`). After this task, `podman compose up postgres` gives a running PG instance for development and testing.

**Files:**
- Modify: `docker-compose.yml`
- Create: `init-db.sh`
- Modify: `Dockerfile`
- Modify: `.gitignore`

- [ ] **Step 1: Write `init-db.sh`**

This script runs on first PG container start to create both databases and users:

```bash
#!/bin/bash
# init-db.sh — creates workbench and zep databases on first PG start
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER workbench WITH PASSWORD 'workbench';
    CREATE DATABASE workbench OWNER workbench;

    CREATE USER zep WITH PASSWORD 'zep';
    CREATE DATABASE zep OWNER zep;

    -- Grant connect permissions
    GRANT ALL PRIVILEGES ON DATABASE workbench TO workbench;
    GRANT ALL PRIVILEGES ON DATABASE zep TO zep;
EOSQL
```

```bash
chmod +x init-db.sh
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
# docker-compose.yml
services:
  postgres:
    image: ghcr.io/getzep/postgres:latest
    network_mode: host
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh:ro
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres

  workbench:
    build: .
    network_mode: host
    depends_on:
      - postgres
    environment:
      WORKBENCH_API_TOKEN: ${WORKBENCH_API_TOKEN:-dev-token}
      WORKBENCH_POSTGRES_DSN: postgres://workbench:workbench@localhost:5432/workbench
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ANTHROPIC_BASE_URL: ${ANTHROPIC_BASE_URL:-https://plugboard.x2p.facebook.net}
      GCHAT_SPACE_ID: ${GCHAT_SPACE_ID:-}
      GOOGLE_API_SCRIPT: ${GOOGLE_API_SCRIPT:-/app/src/workbench/lib/google_api.py}

volumes:
  pgdata:
```

- [ ] **Step 3: Write entrypoint script**

Create `entrypoint.sh`:

```bash
#!/bin/bash
# entrypoint.sh — run migrations then start the server
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Workbench server..."
exec uvicorn workbench.main:app --host 0.0.0.0 --port 8421
```

```bash
chmod +x entrypoint.sh
```

- [ ] **Step 4: Update Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY alembic.ini .
COPY entrypoint.sh .
COPY config.example.yml config.yml
RUN pip install --no-cache-dir -e .
EXPOSE 8421
ENTRYPOINT ["./entrypoint.sh"]
```

- [ ] **Step 5: Update `.gitignore`**

Add these entries if not present:

```
config.yml
.env
docker-compose.override.yml
config.meta.yml
*.pyc
__pycache__/
.venv/
*.egg-info/
```

- [ ] **Step 6: Start PostgreSQL and verify**

```bash
podman compose up -d postgres
sleep 3
podman exec -it $(podman ps -q --filter name=postgres) psql -U postgres -c "\l"
```

Expected: Output shows `workbench` and `zep` databases.

```bash
podman exec -it $(podman ps -q --filter name=postgres) psql -U workbench -d workbench -c "SELECT 1"
```

Expected: Returns `1`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml init-db.sh entrypoint.sh Dockerfile .gitignore && git commit -m "Set up single PostgreSQL instance with dual databases (ADR 0006)"
```

---

## Task 4: YAML Config + Provider Registry

**Goal:** Replace `pydantic-settings` with YAML config loaded via OmegaConf. Implement the provider registry for dynamic import with typed `ProviderConfig` validation. Create `config.example.yml`. Rewrite `main.py` lifespan to use the registry.

**Files:**
- Rewrite: `src/workbench/config.py`
- Create: `src/workbench/registry.py`
- Create: `config.example.yml`
- Create: `alembic.ini`
- Modify: `src/workbench/main.py`
- Create: `tests/test_config.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write `config.py`**

```python
# src/workbench/config.py
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    port: int = 8421
    debug: bool = False
    api_token: str = "dev-token-change-me"


class StorageConfig(BaseModel):
    postgres_dsn: str


class QueueScorerRef(BaseModel):
    """Reference to a QueueScorer provider — resolved by the registry."""
    class_path: str = Field(alias="class", default="workbench.providers.queue_scorer.llm.LLMQueueScorer")
    extra: dict = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class QueueConfig(BaseModel):
    scorer: dict = Field(default_factory=dict)
    worker_concurrency: int = 2
    max_attempts: int = 3
    base_delay_seconds: int = 5


class TriageConfig(BaseModel):
    daily_cap: int = 20
    expiry_days: int = 7
    timeout_minutes: int = 30


class PipelineConfig(BaseModel):
    include_threshold: int = 70
    drop_threshold: int = 30
    confidence_threshold: int = 70


class SchedulerConfig(BaseModel):
    poll_interval_minutes: int = 15
    morning_briefing_hour: int = 9


class AppConfig(BaseModel):
    version: str = "0.1.0"
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig
    llm: dict
    queue: QueueConfig = Field(default_factory=QueueConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    messenger: dict | None = None
    sources: list[dict] = Field(default_factory=list)
    enrichment: dict | None = None
    memory: dict | None = None


def load_config(config_path: str, override_path: str | None = None) -> AppConfig:
    """Load YAML config with OmegaConf env var interpolation and optional override merge."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print("Run 'cp config.example.yml config.yml' and edit it.", file=sys.stderr)
        sys.exit(1)

    base_cfg = OmegaConf.load(config_path)

    if override_path:
        override = OmegaConf.load(override_path)
        base_cfg = OmegaConf.merge(base_cfg, override)

    resolved = OmegaConf.to_container(base_cfg, resolve=True, throw_on_missing=True)

    config = AppConfig(**resolved)

    # Validate config version compatibility
    major = int(config.version.split(".")[0])
    expected_major = 0
    if major != expected_major:
        print(f"Error: Config version {config.version} is incompatible (expected major {expected_major})", file=sys.stderr)
        sys.exit(1)

    return config
```

- [ ] **Step 2: Write `registry.py`**

```python
# src/workbench/registry.py
from __future__ import annotations

import importlib
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    """Base class for provider configs. Providers declare a nested ProviderConfig."""
    pass


def create_provider(section: dict[str, Any]) -> Any:
    """Create a provider instance from a config section with a 'class' key.

    The section must contain a 'class' key with a dotted import path.
    Remaining keys are validated against the provider's ProviderConfig.
    """
    section = dict(section)  # don't mutate the original
    class_path = section.pop("class")
    module_path, class_name = class_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import provider '{class_path}': {e}. "
            f"Check that the package is installed."
        ) from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_path}'")

    if hasattr(cls, "ProviderConfig"):
        typed_config = cls.ProviderConfig(**section)
        return cls(typed_config)
    else:
        return cls(**section) if section else cls()


def create_providers_from_list(sections: list[dict[str, Any]]) -> list[Any]:
    """Create multiple providers from a list of config sections (e.g. sources)."""
    return [create_provider(s) for s in sections]


async def close_provider(provider: Any) -> None:
    """Call close() on a provider if it has one."""
    if hasattr(provider, "close"):
        try:
            await provider.close()
        except Exception as e:
            logger.warning(f"Error closing provider {type(provider).__name__}: {e}")
```

- [ ] **Step 3: Write `config.example.yml`**

```yaml
# config.example.yml — copy to config.yml and edit
version: "0.1.0"

server:
  port: 8421
  debug: false
  api_token: ${oc.env:WORKBENCH_API_TOKEN,dev-token-change-me}

storage:
  postgres_dsn: ${oc.env:WORKBENCH_POSTGRES_DSN,postgres://workbench:workbench@localhost:5432/workbench}

llm:
  class: workbench.providers.llm.claude.ClaudeProvider
  api_key: ${oc.env:ANTHROPIC_API_KEY}
  base_url: ${oc.env:ANTHROPIC_BASE_URL,https://plugboard.x2p.facebook.net}
  model: claude-sonnet-4-20250514

queue:
  scorer:
    class: workbench.providers.queue_scorer.llm.LLMQueueScorer
    api_key: ${oc.env:ANTHROPIC_API_KEY}
    base_url: ${oc.env:ANTHROPIC_BASE_URL,https://plugboard.x2p.facebook.net}
    model: claude-haiku-4-5-20251001
  worker_concurrency: 2
  max_attempts: 3
  base_delay_seconds: 5

triage:
  daily_cap: 20
  expiry_days: 7
  timeout_minutes: 30

pipeline:
  include_threshold: 70
  drop_threshold: 30
  confidence_threshold: 70

scheduler:
  poll_interval_minutes: 15
  morning_briefing_hour: 9

messenger:
  class: workbench.providers.messenger.google_chat.GoogleChatMessenger
  space_id: ${oc.env:GCHAT_SPACE_ID}
  google_api_script: ${oc.env:GOOGLE_API_SCRIPT,src/workbench/lib/google_api.py}

sources: []
# - class: workbench.providers.source.phabricator.PhabricatorAdapter
#   user_phid: ${oc.env:PHABRICATOR_USER_PHID}

enrichment:
  class: workbench.providers.enrichment.stub.StubEnricher

memory:
  class: workbench.memory.noop.NoopMemoryLayer
```

- [ ] **Step 4: Write `alembic.ini`**

```ini
# alembic.ini
[alembic]
script_location = src/workbench/migrations
sqlalchemy.url = postgresql://workbench:workbench@localhost:5432/workbench

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Write config tests**

```python
# tests/test_config.py
import os
import tempfile
import pytest
from workbench.config import load_config, AppConfig


def test_load_config_from_yaml():
    config_content = """
version: "0.1.0"
server:
  port: 9000
  api_token: test-token
storage:
  postgres_dsn: postgres://test:test@localhost:5432/test
llm:
  class: workbench.providers.llm.claude.ClaudeProvider
  api_key: fake-key
  base_url: https://example.com
  model: claude-sonnet-4-20250514
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config = load_config(f.name)

    assert config.server.port == 9000
    assert config.server.api_token == "test-token"
    assert config.storage.postgres_dsn == "postgres://test:test@localhost:5432/test"
    assert config.llm["class"] == "workbench.providers.llm.claude.ClaudeProvider"
    os.unlink(f.name)


def test_config_defaults():
    config_content = """
version: "0.1.0"
storage:
  postgres_dsn: postgres://test:test@localhost:5432/test
llm:
  class: test.Llm
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config = load_config(f.name)

    assert config.server.port == 8421
    assert config.queue.worker_concurrency == 2
    assert config.triage.daily_cap == 20
    assert config.pipeline.include_threshold == 70
    assert config.scheduler.poll_interval_minutes == 15
    assert config.messenger is None
    assert config.sources == []
    os.unlink(f.name)


def test_config_env_interpolation():
    os.environ["TEST_WB_TOKEN"] = "secret-token"
    config_content = """
version: "0.1.0"
server:
  api_token: ${oc.env:TEST_WB_TOKEN}
storage:
  postgres_dsn: postgres://test:test@localhost:5432/test
llm:
  class: test.Llm
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(config_content)
        f.flush()
        config = load_config(f.name)

    assert config.server.api_token == "secret-token"
    os.unlink(f.name)
    del os.environ["TEST_WB_TOKEN"]


def test_config_override_merge():
    base = """
version: "0.1.0"
server:
  port: 8421
  api_token: base-token
storage:
  postgres_dsn: postgres://test:test@localhost:5432/test
llm:
  class: test.Llm
"""
    override = """
server:
  port: 9999
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f1:
        f1.write(base)
        f1.flush()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f2:
            f2.write(override)
            f2.flush()
            config = load_config(f1.name, f2.name)

    assert config.server.port == 9999
    assert config.server.api_token == "base-token"  # not overridden
    os.unlink(f1.name)
    os.unlink(f2.name)
```

- [ ] **Step 6: Write registry tests**

```python
# tests/test_registry.py
import pytest
from pydantic import BaseModel
from workbench.registry import create_provider, close_provider


class FakeProviderConfig(BaseModel):
    name: str = "default"


class FakeProvider:
    ProviderConfig = FakeProviderConfig

    def __init__(self, config: FakeProviderConfig):
        self.name = config.name
        self.closed = False

    async def close(self):
        self.closed = True


def test_create_provider_with_config():
    section = {"class": "tests.test_registry.FakeProvider", "name": "test"}
    provider = create_provider(section)
    assert isinstance(provider, FakeProvider)
    assert provider.name == "test"


def test_create_provider_default_config():
    section = {"class": "tests.test_registry.FakeProvider"}
    provider = create_provider(section)
    assert provider.name == "default"


def test_create_provider_bad_class():
    with pytest.raises(ImportError):
        create_provider({"class": "nonexistent.module.Class"})


async def test_close_provider():
    provider = FakeProvider(FakeProviderConfig(name="x"))
    await close_provider(provider)
    assert provider.closed is True


async def test_close_provider_without_close_method():
    class NoClose:
        pass
    await close_provider(NoClose())  # should not raise
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_config.py tests/test_registry.py -v
```

Expected: All tests pass.

- [ ] **Step 8: Rewrite `main.py` with registry-based lifespan**

```python
# src/workbench/main.py
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from workbench import __version__
from workbench.auth import BearerTokenMiddleware
from workbench.config import AppConfig, load_config
from workbench.memory.noop import NoopMemoryLayer
from workbench.registry import close_provider, create_provider
from workbench.storage.factory import create_stores

logger = logging.getLogger(__name__)


def get_config() -> AppConfig:
    config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")
    override_path = os.environ.get("WORKBENCH_CONFIG_OVERRIDE")
    return load_config(config_path, override_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config

    # Storage
    app.state.stores = await create_stores(config)

    # Providers via registry
    app.state.llm = create_provider(config.llm)

    if config.messenger:
        app.state.messenger = create_provider(config.messenger)
    else:
        app.state.messenger = None

    if config.enrichment:
        app.state.enricher = create_provider(config.enrichment)
    else:
        from workbench.providers.enrichment.stub import StubEnricher
        app.state.enricher = StubEnricher()

    if config.memory:
        app.state.memory = create_provider(config.memory)
    else:
        app.state.memory = NoopMemoryLayer()

    if config.queue.scorer:
        app.state.queue_scorer = create_provider(config.queue.scorer)
    else:
        app.state.queue_scorer = None

    app.state.sources = []
    for source_cfg in config.sources:
        app.state.sources.append(create_provider(source_cfg))

    # Pipeline engine
    from workbench.pipeline.engine import PipelineEngine
    app.state.pipeline = PipelineEngine(
        app.state.stores, app.state.memory, app.state.llm, app.state.enricher
    )

    # Ingestion queue worker
    from workbench.pipeline.worker import IngestionQueueWorker
    app.state.worker = IngestionQueueWorker(
        stores=app.state.stores,
        pipeline=app.state.pipeline,
        concurrency=config.queue.worker_concurrency,
    )
    app.state.worker.start()

    # Scheduler
    from workbench.pipeline.scheduler import WorkbenchScheduler
    app.state.scheduler = WorkbenchScheduler(
        stores=app.state.stores,
        memory=app.state.memory,
        pipeline=app.state.pipeline,
        messenger=app.state.messenger,
        config=config,
    )
    app.state.scheduler.start()

    yield

    # Cleanup
    app.state.worker.stop()
    app.state.scheduler.scheduler.shutdown(wait=False)

    for provider in [app.state.llm, app.state.messenger, app.state.enricher,
                     app.state.memory, app.state.queue_scorer]:
        if provider:
            await close_provider(provider)
    for source in app.state.sources:
        await close_provider(source)

    await app.state.stores.close()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="Workbench", version=__version__, lifespan=lifespan)
    app.add_middleware(BearerTokenMiddleware, token=config.server.api_token)

    from workbench.api import (
        config as config_api, filter_rules, health, items, jobs,
        memory, process, queue, sources, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, jobs.router, queue.router,
    ]:
        app.include_router(r)

    return app


app = create_app()


def cli_main():
    import uvicorn
    config = get_config()
    uvicorn.run("workbench.main:app", host="0.0.0.0", port=config.server.port,
                reload=config.server.debug)
```

Note: This references `queue.router` and `IngestionQueueWorker` which don't exist yet — they'll be created in later tasks. For now, comment out those lines and add a placeholder:

```python
# TODO: uncomment after Task 7 (queue) and Task 8 (worker)
# from workbench.api import queue
# app.state.worker = IngestionQueueWorker(...)
# app.state.worker.start()
```

- [ ] **Step 9: Commit**

```bash
git add src/workbench/config.py src/workbench/registry.py src/workbench/main.py \
  config.example.yml alembic.ini tests/test_config.py tests/test_registry.py \
  && git commit -m "Add YAML config with OmegaConf, provider registry with typed ProviderConfig (ADR 0005)"
```

---

## Task 5: Storage Interfaces + Alembic

**Goal:** Update the repository ABCs to include `IngestionQueueStore` and triage queue columns. Set up Alembic with asyncpg and write the initial migration.

**Files:**
- Modify: `src/workbench/storage/base.py`
- Modify: `src/workbench/storage/factory.py`
- Create: `src/workbench/migrations/env.py`
- Create: `src/workbench/migrations/script.py.mako`
- Create: `src/workbench/migrations/versions/001_initial_schema.py`

- [ ] **Step 1: Update `storage/base.py` with `IngestionQueueStore` and updated `TriageStore`**

```python
# src/workbench/storage/base.py
from __future__ import annotations

from abc import ABC, abstractmethod

from workbench.models import (
    EnrichmentTrace,
    FilterRule,
    IngestionQueueEntry,
    InteractionEntry,
    Item,
    ItemFilters,
    ItemUpdate,
    PipelineJob,
    Plan,
    PlanFilters,
    PlanUpdate,
    SourceConfig,
    SourceConfigUpdate,
    TraceFilters,
    TriageCard,
    TriageResponse,
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
    async def get_next_unsent(self) -> TriageCard | None: ...
    @abstractmethod
    async def save_card(self, card: TriageCard) -> TriageCard: ...
    @abstractmethod
    async def update_card(self, card: TriageCard) -> None: ...
    @abstractmethod
    async def record_response(self, card_id: str, response: TriageResponse) -> None: ...
    @abstractmethod
    async def get_card(self, card_id: str) -> TriageCard | None: ...
    @abstractmethod
    async def expire_old_cards(self, expiry_days: int) -> int: ...
    @abstractmethod
    async def count_sent_today(self) -> int: ...


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
    async def get_source(self, source_id: str) -> SourceConfig | None: ...
    @abstractmethod
    async def upsert_source(self, source: SourceConfig) -> SourceConfig: ...
    @abstractmethod
    async def update_source(self, source_id: str, updates: SourceConfigUpdate) -> SourceConfig: ...


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


class IngestionQueueStore(ABC):
    @abstractmethod
    async def enqueue(self, entry: IngestionQueueEntry) -> IngestionQueueEntry: ...
    @abstractmethod
    async def dequeue(self, limit: int = 1) -> list[IngestionQueueEntry]: ...
    @abstractmethod
    async def mark_completed(self, entry_id: str) -> None: ...
    @abstractmethod
    async def mark_failed(self, entry_id: str, error: str) -> None: ...
    @abstractmethod
    async def get_dead_letters(self) -> list[IngestionQueueEntry]: ...
    @abstractmethod
    async def retry_dead_letter(self, entry_id: str) -> None: ...
    @abstractmethod
    async def purge_dead_letter(self, entry_id: str) -> None: ...
    @abstractmethod
    async def recover_stuck(self) -> int: ...
    @abstractmethod
    async def queue_depth(self) -> int: ...


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
        ingestion_queue: IngestionQueueStore,
        close_fn=None,
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
        self.ingestion_queue = ingestion_queue
        self._close_fn = close_fn

    async def close(self):
        if self._close_fn:
            await self._close_fn()
```

- [ ] **Step 2: Update `storage/factory.py`**

```python
# src/workbench/storage/factory.py
from workbench.config import AppConfig
from workbench.storage.base import Stores


async def create_stores(config: AppConfig) -> Stores:
    from workbench.storage.postgres import create_postgres_stores
    return await create_postgres_stores(config.storage.postgres_dsn)
```

- [ ] **Step 3: Create Alembic migration environment**

```python
# src/workbench/migrations/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

```mako
## src/workbench/migrations/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Write initial migration**

```python
# src/workbench/migrations/versions/001_initial_schema.py
"""Initial schema — all tables for Phase 1a.

Revision ID: 001
Revises: None
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("origin", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("raw_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_items_status_priority", "items", ["status", "priority"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("sources", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "triage_cards",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text),
        sa.Column("card_content", JSONB, nullable=False, server_default="{}"),
        sa.Column("options", JSONB, nullable=False, server_default="[]"),
        sa.Column("relevance_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("confidence_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("bot_message_id", sa.Text),
        sa.Column("daily_sequence", sa.Integer),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("response", sa.Text),
    )
    op.create_index("idx_triage_status", "triage_cards", ["status"])
    op.create_index("idx_triage_relevance", "triage_cards", ["relevance_score"])

    op.create_table(
        "interaction_log",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("item_id", sa.Text),
        sa.Column("item_summary", sa.Text, nullable=False),
        sa.Column("triage_card_full", JSONB, nullable=False, server_default="{}"),
        sa.Column("enrichment_context", JSONB, nullable=False, server_default="{}"),
        sa.Column("options_presented", JSONB, nullable=False, server_default="[]"),
        sa.Column("option_chosen", sa.Text, nullable=False, server_default=""),
        sa.Column("todo_created", JSONB),
        sa.Column("enrichment_depth", sa.Text, nullable=False, server_default="none"),
        sa.Column("enrichment_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enrichment_time_ms", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "filter_rules",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_type", sa.Text),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("priority", sa.Text),
        sa.Column("created_from_interaction_id", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "enrichment_trace",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("item_id", sa.Text, nullable=False),
        sa.Column("depth", sa.Text, nullable=False),
        sa.Column("calls_made", sa.Integer, nullable=False),
        sa.Column("time_ms", sa.Integer, nullable=False),
        sa.Column("context_retrieved", JSONB, nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "processed",
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("source_type", "source_id"),
    )

    op.create_table(
        "source_configs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("adapter_type", sa.Text, nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("schedule", sa.Text, nullable=False, server_default="*/15 * * * *"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("input_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("items_extracted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_included", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_triaged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_dropped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "config",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )

    op.create_table(
        "ingestion_queue",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("raw_content", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text),
        sa.Column("urgency_signals", JSONB, nullable=False, server_default="{}"),
        sa.Column("urgency_score", sa.Integer, nullable=False),
        sa.Column("job_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_iq_status_urgency", "ingestion_queue", ["status", "urgency_score"])
    op.create_index("idx_iq_next_retry", "ingestion_queue", ["next_retry_at"])


def downgrade() -> None:
    for table in ["ingestion_queue", "config", "jobs", "source_configs", "processed",
                  "enrichment_trace", "filter_rules", "interaction_log", "triage_cards",
                  "plans", "items"]:
        op.drop_table(table)
```

- [ ] **Step 5: Run migration against the running PG**

Ensure PG is running:

```bash
podman compose up -d postgres
```

Add `sqlalchemy[asyncio]` and `asyncpg` to pyproject.toml if not already present (they are — `asyncpg` is listed). Also add `sqlalchemy>=2.0` for Alembic's async support:

```bash
pip install sqlalchemy[asyncio]>=2.0
```

Run the migration:

```bash
alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema`

Verify tables exist:

```bash
podman exec -it $(podman ps -q --filter name=postgres) psql -U workbench -d workbench -c "\dt"
```

Expected: All 11 tables listed.

- [ ] **Step 6: Commit**

```bash
git add src/workbench/storage/base.py src/workbench/storage/factory.py \
  src/workbench/migrations/ alembic.ini \
  && git commit -m "Add storage interfaces with IngestionQueueStore, Alembic migrations (ADR 0006, 0007)"
```

---

## Task 6: PostgreSQL Storage Implementation

**Goal:** Implement all stores using asyncpg. Replace the SQLite implementations. Each store follows the same pattern: receive a connection pool, execute parameterized queries, return domain models.

**Files:**
- Create: `src/workbench/storage/postgres/__init__.py`
- Create: `src/workbench/storage/postgres/pool.py`
- Create: `src/workbench/storage/postgres/items.py`
- Create: `src/workbench/storage/postgres/triage.py`
- Create: `src/workbench/storage/postgres/plans.py`
- Create: `src/workbench/storage/postgres/interactions.py`
- Create: `src/workbench/storage/postgres/filter_rules.py`
- Create: `src/workbench/storage/postgres/enrichment.py`
- Create: `src/workbench/storage/postgres/sources.py`
- Create: `src/workbench/storage/postgres/processed.py`
- Create: `src/workbench/storage/postgres/config.py`
- Create: `src/workbench/storage/postgres/jobs.py`
- Create: `src/workbench/storage/postgres/ingestion_queue.py`
- Rewrite: `tests/test_storage.py`
- Create: `tests/conftest.py`
- Delete: `src/workbench/storage/sqlite/` (entire directory)

- [ ] **Step 1: Write connection pool manager**

```python
# src/workbench/storage/postgres/pool.py
import asyncpg


async def create_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
```

- [ ] **Step 2: Write PgItemStore**

```python
# src/workbench/storage/postgres/items.py
from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from workbench.models import Item, ItemFilters, ItemUpdate
from workbench.storage.base import ItemStore


class PgItemStore(ItemStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_items(self, filters: ItemFilters) -> list[Item]:
        query = "SELECT * FROM items WHERE true"
        params = []
        idx = 1
        if filters.status:
            query += f" AND status = ${idx}"
            params.append(filters.status.value)
            idx += 1
        if filters.priority:
            query += f" AND priority = ${idx}"
            params.append(filters.priority.value)
            idx += 1
        if filters.source_type:
            query += f" AND source_type = ${idx}"
            params.append(filters.source_type)
            idx += 1
        if filters.category:
            query += f" AND category = ${idx}"
            params.append(filters.category.value)
            idx += 1
        query += " ORDER BY created_at DESC"
        rows = await self.pool.fetch(query, *params)
        return [self._row_to_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Item | None:
        row = await self.pool.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
        return self._row_to_item(row) if row else None

    async def save_item(self, item: Item) -> Item:
        await self.pool.execute(
            """INSERT INTO items (id, source_type, source_id, summary, category, origin,
               priority, status, raw_data, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            item.id, item.source_type, item.source_id, item.summary,
            item.category.value, item.origin.value, item.priority.value,
            item.status.value, json.dumps(item.raw_data),
            item.created_at, item.updated_at,
        )
        return item

    async def update_item(self, item_id: str, updates: ItemUpdate) -> Item:
        sets, params = [], []
        idx = 1
        if updates.priority is not None:
            sets.append(f"priority = ${idx}")
            params.append(updates.priority.value)
            idx += 1
        if updates.status is not None:
            sets.append(f"status = ${idx}")
            params.append(updates.status.value)
            idx += 1
        if updates.summary is not None:
            sets.append(f"summary = ${idx}")
            params.append(updates.summary)
            idx += 1
        sets.append("updated_at = now()")
        params.append(item_id)
        await self.pool.execute(
            f"UPDATE items SET {', '.join(sets)} WHERE id = ${idx}", *params
        )
        return await self.get_item(item_id)

    async def archive_item(self, item_id: str) -> None:
        await self.pool.execute(
            "UPDATE items SET status = 'archived', updated_at = now() WHERE id = $1",
            item_id,
        )

    def _row_to_item(self, row: asyncpg.Record) -> Item:
        raw_data = row["raw_data"]
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        return Item(
            id=row["id"], source_type=row["source_type"], source_id=row["source_id"],
            summary=row["summary"], category=row["category"], origin=row["origin"],
            priority=row["priority"], status=row["status"], raw_data=raw_data,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
```

- [ ] **Step 3: Write PgTriageStore (with queue columns)**

```python
# src/workbench/storage/postgres/triage.py
from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from workbench.models import TriageCard, TriageOption, TriageResponse
from workbench.storage.base import TriageStore


class PgTriageStore(TriageStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_pending(self) -> list[TriageCard]:
        rows = await self.pool.fetch(
            "SELECT * FROM triage_cards WHERE status IN ('queued', 'sent') "
            "ORDER BY relevance_score DESC"
        )
        return [self._row_to_card(r) for r in rows]

    async def get_next_unsent(self) -> TriageCard | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM triage_cards WHERE status = 'queued' "
            "ORDER BY relevance_score DESC LIMIT 1"
        )
        return self._row_to_card(row) if row else None

    async def save_card(self, card: TriageCard) -> TriageCard:
        options_json = json.dumps([o.model_dump() for o in card.options])
        await self.pool.execute(
            """INSERT INTO triage_cards (id, item_id, card_content, options,
               relevance_score, confidence_score, status, bot_message_id,
               daily_sequence, expires_at, sent_at, responded_at, response)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (id) DO UPDATE SET
               card_content=$3, options=$4, relevance_score=$5, confidence_score=$6,
               status=$7, bot_message_id=$8, daily_sequence=$9, expires_at=$10,
               sent_at=$11, responded_at=$12, response=$13""",
            card.id, card.item_id, json.dumps(card.card_content), options_json,
            card.relevance_score, card.confidence_score, card.status,
            card.bot_message_id, card.daily_sequence, card.expires_at,
            card.sent_at, card.responded_at, card.response,
        )
        return card

    async def update_card(self, card: TriageCard) -> None:
        await self.save_card(card)

    async def record_response(self, card_id: str, response: TriageResponse) -> None:
        await self.pool.execute(
            "UPDATE triage_cards SET responded_at = now(), response = $2, status = 'responded' WHERE id = $1",
            card_id, str(response.choice),
        )

    async def get_card(self, card_id: str) -> TriageCard | None:
        row = await self.pool.fetchrow("SELECT * FROM triage_cards WHERE id = $1", card_id)
        return self._row_to_card(row) if row else None

    async def expire_old_cards(self, expiry_days: int) -> int:
        result = await self.pool.execute(
            "UPDATE triage_cards SET status = 'expired' "
            "WHERE status = 'queued' AND expires_at < now()"
        )
        return int(result.split()[-1])

    async def count_sent_today(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as cnt FROM triage_cards "
            "WHERE sent_at >= CURRENT_DATE AND status IN ('sent', 'responded')"
        )
        return row["cnt"]

    def _row_to_card(self, row: asyncpg.Record) -> TriageCard:
        card_content = row["card_content"]
        if isinstance(card_content, str):
            card_content = json.loads(card_content)
        options_raw = row["options"]
        if isinstance(options_raw, str):
            options_raw = json.loads(options_raw)
        options = [TriageOption(**o) for o in options_raw]
        return TriageCard(
            id=row["id"], item_id=row["item_id"], card_content=card_content,
            options=options, relevance_score=row["relevance_score"],
            confidence_score=row["confidence_score"], status=row["status"],
            bot_message_id=row["bot_message_id"], daily_sequence=row["daily_sequence"],
            expires_at=row["expires_at"], sent_at=row["sent_at"],
            responded_at=row["responded_at"], response=row["response"],
        )
```

- [ ] **Step 4: Write PgIngestionQueueStore**

```python
# src/workbench/storage/postgres/ingestion_queue.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import asyncpg

from workbench.models import IngestionQueueEntry, QueueEntryStatus
from workbench.storage.base import IngestionQueueStore


class PgIngestionQueueStore(IngestionQueueStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def enqueue(self, entry: IngestionQueueEntry) -> IngestionQueueEntry:
        await self.pool.execute(
            """INSERT INTO ingestion_queue
               (id, raw_content, source_type, source_id, urgency_signals,
                urgency_score, job_id, status, attempt, max_attempts,
                next_retry_at, error, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
            entry.id, entry.raw_content, entry.source_type, entry.source_id,
            json.dumps(entry.urgency_signals), entry.urgency_score, entry.job_id,
            entry.status.value, entry.attempt, entry.max_attempts,
            entry.next_retry_at, entry.error, entry.created_at, entry.updated_at,
        )
        return entry

    async def dequeue(self, limit: int = 1) -> list[IngestionQueueEntry]:
        rows = await self.pool.fetch(
            """UPDATE ingestion_queue SET status = 'processing', attempt = attempt + 1,
               updated_at = now()
               WHERE id IN (
                   SELECT id FROM ingestion_queue
                   WHERE status = 'queued'
                     AND (next_retry_at IS NULL OR next_retry_at <= now())
                   ORDER BY urgency_score DESC
                   LIMIT $1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            limit,
        )
        return [self._row_to_entry(r) for r in rows]

    async def mark_completed(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'completed', updated_at = now() WHERE id = $1",
            entry_id,
        )

    async def mark_failed(self, entry_id: str, error: str) -> None:
        row = await self.pool.fetchrow(
            "SELECT attempt, max_attempts FROM ingestion_queue WHERE id = $1", entry_id
        )
        if not row:
            return
        if row["attempt"] >= row["max_attempts"]:
            await self.pool.execute(
                "UPDATE ingestion_queue SET status = 'dead_letter', error = $2, updated_at = now() WHERE id = $1",
                entry_id, error,
            )
        else:
            delay = (2 ** row["attempt"]) * 5
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            await self.pool.execute(
                "UPDATE ingestion_queue SET status = 'queued', error = $2, next_retry_at = $3, updated_at = now() WHERE id = $1",
                entry_id, error, retry_at,
            )

    async def get_dead_letters(self) -> list[IngestionQueueEntry]:
        rows = await self.pool.fetch(
            "SELECT * FROM ingestion_queue WHERE status = 'dead_letter' ORDER BY created_at DESC"
        )
        return [self._row_to_entry(r) for r in rows]

    async def retry_dead_letter(self, entry_id: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'queued', attempt = 0, next_retry_at = NULL, "
            "error = NULL, updated_at = now() WHERE id = $1 AND status = 'dead_letter'",
            entry_id,
        )

    async def purge_dead_letter(self, entry_id: str) -> None:
        await self.pool.execute(
            "DELETE FROM ingestion_queue WHERE id = $1 AND status = 'dead_letter'",
            entry_id,
        )

    async def recover_stuck(self) -> int:
        result = await self.pool.execute(
            "UPDATE ingestion_queue SET status = 'queued', updated_at = now() "
            "WHERE status = 'processing'"
        )
        return int(result.split()[-1])

    async def queue_depth(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as cnt FROM ingestion_queue WHERE status IN ('queued', 'processing')"
        )
        return row["cnt"]

    def _row_to_entry(self, row: asyncpg.Record) -> IngestionQueueEntry:
        signals = row["urgency_signals"]
        if isinstance(signals, str):
            signals = json.loads(signals)
        return IngestionQueueEntry(
            id=row["id"], raw_content=row["raw_content"], source_type=row["source_type"],
            source_id=row["source_id"], urgency_signals=signals,
            urgency_score=row["urgency_score"], job_id=row["job_id"],
            status=row["status"], attempt=row["attempt"], max_attempts=row["max_attempts"],
            next_retry_at=row["next_retry_at"], error=row["error"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
```

- [ ] **Step 5: Write remaining PG stores**

Create each file following the same pattern as `PgItemStore`. Each receives `pool: asyncpg.Pool` and executes parameterized queries.

`src/workbench/storage/postgres/plans.py` — `PgPlanStore` (get_plans, save_plan, update_plan)
`src/workbench/storage/postgres/interactions.py` — `PgInteractionStore` (append, get_since, count, get_all)
`src/workbench/storage/postgres/filter_rules.py` — `PgFilterRuleStore` (get_rules, add_rule, get_source_rules)
`src/workbench/storage/postgres/enrichment.py` — `PgEnrichmentTraceStore` (log_trace, get_traces)
`src/workbench/storage/postgres/sources.py` — `PgSourceConfigStore` (get_sources, get_source, upsert_source, update_source)
`src/workbench/storage/postgres/processed.py` — `PgProcessedStore` (is_processed, mark_processed)
`src/workbench/storage/postgres/config.py` — `PgConfigStore` (get, set, get_all)
`src/workbench/storage/postgres/jobs.py` — `PgJobStore` (save_job, get_job, update_job)

Reference the existing SQLite implementations in `src/workbench/storage/sqlite/` for the business logic — translate the SQL from SQLite to PostgreSQL (use `$N` params instead of `?`, `JSONB` instead of `TEXT` for JSON columns, `now()` instead of `datetime('now')`). Each store module should be ~40-80 lines.

- [ ] **Step 6: Write `__init__.py` to assemble all stores**

```python
# src/workbench/storage/postgres/__init__.py
from workbench.storage.base import Stores
from workbench.storage.postgres.pool import create_pool
from workbench.storage.postgres.items import PgItemStore
from workbench.storage.postgres.triage import PgTriageStore
from workbench.storage.postgres.plans import PgPlanStore
from workbench.storage.postgres.interactions import PgInteractionStore
from workbench.storage.postgres.filter_rules import PgFilterRuleStore
from workbench.storage.postgres.enrichment import PgEnrichmentTraceStore
from workbench.storage.postgres.sources import PgSourceConfigStore
from workbench.storage.postgres.processed import PgProcessedStore
from workbench.storage.postgres.config import PgConfigStore
from workbench.storage.postgres.jobs import PgJobStore
from workbench.storage.postgres.ingestion_queue import PgIngestionQueueStore


async def create_postgres_stores(dsn: str) -> Stores:
    pool = await create_pool(dsn)

    async def close():
        await pool.close()

    return Stores(
        items=PgItemStore(pool),
        triage=PgTriageStore(pool),
        plans=PgPlanStore(pool),
        interactions=PgInteractionStore(pool),
        filter_rules=PgFilterRuleStore(pool),
        enrichment=PgEnrichmentTraceStore(pool),
        sources=PgSourceConfigStore(pool),
        processed=PgProcessedStore(pool),
        config=PgConfigStore(pool),
        jobs=PgJobStore(pool),
        ingestion_queue=PgIngestionQueueStore(pool),
        close_fn=close,
    )
```

- [ ] **Step 7: Write test fixtures**

```python
# tests/conftest.py
import asyncio
import pytest
import asyncpg

TEST_DSN = "postgres://workbench:workbench@localhost:5432/workbench"

TABLES = [
    "ingestion_queue", "config", "jobs", "source_configs", "processed",
    "enrichment_trace", "filter_rules", "interaction_log", "triage_cards",
    "plans", "items",
]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5)
    # Truncate all tables before each test
    for table in TABLES:
        await pool.execute(f"TRUNCATE {table} CASCADE")
    yield pool
    await pool.close()


@pytest.fixture
async def stores(pg_pool):
    from workbench.storage.postgres import create_postgres_stores
    s = await create_postgres_stores(TEST_DSN)
    # Truncate all tables
    for table in TABLES:
        await pg_pool.execute(f"TRUNCATE {table} CASCADE")
    yield s
    await s.close()
```

- [ ] **Step 8: Write storage tests**

```python
# tests/test_storage.py
import pytest
from workbench.models import (
    Item, ItemCategory, ItemOrigin, Priority, ItemStatus, ItemFilters, ItemUpdate,
    FilterRule, InteractionEntry, TriageCard, TriageOption, TriageResponse,
    PipelineJob, JobTrigger, JobStatus,
    IngestionQueueEntry, QueueEntryStatus,
)


@pytest.mark.asyncio
async def test_item_crud(stores):
    item = Item(source_type="diff", source_id="D123", summary="test",
                category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P1)
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
    await stores.items.save_item(Item(source_type="diff", source_id="D1", summary="a",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL, priority=Priority.P0))
    await stores.items.save_item(Item(source_type="email", source_id="E1", summary="b",
        category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.MANUAL, priority=Priority.P3))
    results = await stores.items.get_items(ItemFilters(priority=Priority.P0))
    assert len(results) == 1
    assert results[0].source_id == "D1"


@pytest.mark.asyncio
async def test_filter_rules(stores):
    rule = FilterRule(pattern="CI bot comments", action="drop")
    await stores.filter_rules.add_rule(rule)
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
    card = TriageCard(
        card_content={"summary": "test"},
        options=[TriageOption(label="Skip", action="skip")],
        relevance_score=75,
    )
    await stores.triage.save_card(card)
    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].relevance_score == 75

    await stores.triage.record_response(card.id, TriageResponse(card_id=card.id, choice=1))
    pending = await stores.triage.get_pending()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_triage_next_unsent(stores):
    card1 = TriageCard(card_content={"summary": "low"}, relevance_score=30)
    card2 = TriageCard(card_content={"summary": "high"}, relevance_score=90)
    await stores.triage.save_card(card1)
    await stores.triage.save_card(card2)
    next_card = await stores.triage.get_next_unsent()
    assert next_card.relevance_score == 90


@pytest.mark.asyncio
async def test_job_tracking(stores):
    job = PipelineJob(trigger=JobTrigger.MANUAL, status=JobStatus.QUEUED)
    await stores.jobs.save_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched.status == JobStatus.QUEUED
    job.status = JobStatus.COMPLETED
    job.items_extracted = 5
    await stores.jobs.update_job(job)
    fetched = await stores.jobs.get_job(job.id)
    assert fetched.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_ingestion_queue_enqueue_dequeue(stores):
    entry = IngestionQueueEntry(
        raw_content="test content", source_type="manual", job_id="j1",
        urgency_score=80,
    )
    await stores.ingestion_queue.enqueue(entry)
    assert await stores.ingestion_queue.queue_depth() == 1

    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    assert len(dequeued) == 1
    assert dequeued[0].status == QueueEntryStatus.PROCESSING
    assert dequeued[0].urgency_score == 80

    await stores.ingestion_queue.mark_completed(dequeued[0].id)
    assert await stores.ingestion_queue.queue_depth() == 0


@pytest.mark.asyncio
async def test_ingestion_queue_dead_letter(stores):
    entry = IngestionQueueEntry(
        raw_content="bad content", source_type="manual", job_id="j2",
        urgency_score=50, max_attempts=1,
    )
    await stores.ingestion_queue.enqueue(entry)
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    await stores.ingestion_queue.mark_failed(dequeued[0].id, "test error")

    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 1

    await stores.ingestion_queue.retry_dead_letter(dead[0].id)
    dead = await stores.ingestion_queue.get_dead_letters()
    assert len(dead) == 0
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_ingestion_queue_priority_ordering(stores):
    e1 = IngestionQueueEntry(raw_content="low", source_type="email", job_id="j3", urgency_score=20)
    e2 = IngestionQueueEntry(raw_content="high", source_type="diff", job_id="j4", urgency_score=90)
    await stores.ingestion_queue.enqueue(e1)
    await stores.ingestion_queue.enqueue(e2)
    dequeued = await stores.ingestion_queue.dequeue(limit=1)
    assert dequeued[0].urgency_score == 90  # highest urgency first
```

- [ ] **Step 9: Run storage tests**

```bash
python -m pytest tests/test_storage.py -v
```

Expected: All tests pass against the running PG instance.

- [ ] **Step 10: Delete SQLite storage directory**

```bash
rm -rf src/workbench/storage/sqlite
```

- [ ] **Step 11: Commit**

```bash
git add src/workbench/storage/postgres/ tests/conftest.py tests/test_storage.py \
  && git rm -rf src/workbench/storage/sqlite \
  && git commit -m "Implement PostgreSQL storage, delete SQLite (ADR 0006)"
```

---

## Task 7: Provider Updates

**Goal:** Add `ProviderConfig` and `close()` to all providers. Switch `GoogleChatMessenger` and `PhabricatorAdapter` from `subprocess.run` to `asyncio.create_subprocess_exec`.

**Files:**
- Modify: `src/workbench/providers/llm/base.py`, `src/workbench/providers/llm/claude.py`
- Modify: `src/workbench/providers/messenger/base.py`, `src/workbench/providers/messenger/google_chat.py`
- Modify: `src/workbench/providers/source/base.py`, `src/workbench/providers/source/phabricator.py`, `src/workbench/providers/source/email_gmail.py`
- Modify: `src/workbench/providers/enrichment/base.py`, `src/workbench/providers/enrichment/stub.py`
- Modify: `src/workbench/providers/doc_reader/base.py`
- Modify: `src/workbench/memory/base.py`, `src/workbench/memory/noop.py`

- [ ] **Step 1: Add `close()` to all base ABCs**

In each base ABC file, add a default `close()` method:

`src/workbench/providers/llm/base.py`:
```python
from abc import ABC, abstractmethod
from workbench.models import ExtractedItem, FilterRule, TriageCard, Fact

class LLMProvider(ABC):
    @abstractmethod
    async def extract(self, raw_text: str, source_type: str) -> list[ExtractedItem]: ...
    @abstractmethod
    async def score_relevance(self, item: ExtractedItem, preference_facts: list[Fact], rules: list[FilterRule]) -> tuple[int, int]: ...
    @abstractmethod
    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard: ...
    async def close(self) -> None: pass
```

Apply the same `async def close(self) -> None: pass` to `Messenger`, `SourceAdapter`, `ContextEnricher`, `DocReader`, and `MemoryLayer` ABCs.

- [ ] **Step 2: Add `ProviderConfig` to `ClaudeProvider`**

```python
# src/workbench/providers/llm/claude.py
import json
import asyncio
import os
import ssl
import httpx
from pydantic import BaseModel
from anthropic import AsyncAnthropic
from workbench.providers.llm.base import LLMProvider
from workbench.models import ExtractedItem, ItemCategory, RawItem, FilterRule, TriageCard, TriageOption, Fact

EXTRACT_PROMPT = """Extract actionable items from the following content. For each item, provide:
- summary: what needs to be done or noted
- category: one of "action_item", "meeting", "plan_seed", "informational"
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
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://plugboard.x2p.facebook.net"
        model: str = "claude-sonnet-4-20250514"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        self._http_client = None
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            self._http_client = httpx.AsyncClient(verify=ssl_ctx)
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    # extract, score_relevance, generate_triage_card, _template_options,
    # _call_with_retry, _extract_json — keep existing implementations unchanged
    # (copy from current server/providers/llm/claude.py, already correct)

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
            SCORE_PROMPT.format(summary=item.summary, source_type=item.raw_item.source_type,
                               preferences=prefs_text, rules=rules_text)
        )
        try:
            scores = json.loads(self._extract_json(response))
            return int(scores["relevance"]), int(scores["confidence"])
        except (json.JSONDecodeError, KeyError):
            return 50, 30

    async def generate_triage_card(self, item: ExtractedItem, enrichment_context: dict, source_type: str) -> TriageCard:
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
                    model=self.model, max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    def _extract_json(self, text: str) -> str:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()
```

- [ ] **Step 3: Add `ProviderConfig` to `GoogleChatMessenger` and switch to async subprocess**

```python
# src/workbench/providers/messenger/google_chat.py
import asyncio
import json
from pydantic import BaseModel
from workbench.providers.messenger.base import Messenger


class GoogleChatMessenger(Messenger):
    class ProviderConfig(BaseModel):
        space_id: str
        google_api_script: str = "src/workbench/lib/google_api.py"

    def __init__(self, config: ProviderConfig):
        self.space_id = config.space_id
        self.script = config.google_api_script

    async def send_card(self, card_text: str) -> str:
        result = await self._run({"action": "send_message", "space_id": self.space_id,
                                  "text": card_text, "as_bot": True})
        if result.get("success"):
            return result["data"].get("name", "")
        raise RuntimeError(f"Failed to send message: {result.get('error', 'unknown')}")

    async def poll_responses(self, since_message_id: str | None = None) -> list[dict]:
        result = await self._run({"action": "list_messages", "space_id": self.space_id})
        if not result.get("success"):
            return []
        messages = result["data"].get("messages", [])
        human_msgs = [m for m in messages if m.get("sender_type") == "HUMAN"]
        if since_message_id:
            found = False
            filtered = []
            for m in human_msgs:
                if found:
                    filtered.append(m)
                if m.get("name") == since_message_id:
                    found = True
            return filtered
        return human_msgs

    async def _run(self, params: dict) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "python3", self.script, json.dumps(params),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return {"success": False, "error": stderr.decode()}
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
```

- [ ] **Step 4: Add `ProviderConfig` to `PhabricatorAdapter` and switch to async subprocess**

```python
# src/workbench/providers/source/phabricator.py
import asyncio
import json
from datetime import datetime
from pydantic import BaseModel
from workbench.providers.source.base import SourceAdapter
from workbench.models import RawItem


class PhabricatorAdapter(SourceAdapter):
    class ProviderConfig(BaseModel):
        user_phid: str = ""

    def __init__(self, config: ProviderConfig):
        self.user_phid = config.user_phid

    def adapter_type(self) -> str:
        return "diff"

    async def poll(self, config: dict, since: datetime | None = None) -> list[RawItem]:
        if not self.user_phid:
            return []
        items = []
        items.extend(await self._query_diffs({"authorPHIDs": [self.user_phid]}, since))
        items.extend(await self._query_diffs({"reviewerPHIDs": [self.user_phid]}, since))
        return items

    async def _query_diffs(self, constraints: dict, since: datetime | None) -> list[RawItem]:
        if since:
            constraints["modifiedStart"] = int(since.timestamp())
        params = {"constraints": constraints, "limit": 50}
        result = await self._conduit_call("differential.revision.search", params)
        if not result:
            return []
        items = []
        for rev in result.get("data", []):
            rev_id = rev["id"]
            mod_time = rev["fields"].get("dateModified", 0)
            fields = rev.get("fields", {})
            items.append(RawItem(
                id=f"D{rev_id}_{mod_time}",
                source_type="diff",
                source_label=f"D{rev_id} — {fields.get('title', '')}",
                raw_text=json.dumps(fields),
                urgency_signals={
                    "status": fields.get("status", {}).get("value", ""),
                },
            ))
        return items

    async def _conduit_call(self, method: str, params: dict) -> dict | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "arc", "call-conduit", method,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=json.dumps(params).encode()), timeout=30
            )
            if proc.returncode != 0:
                return None
            return json.loads(stdout.decode()).get("response", {})
        except Exception:
            return None
```

- [ ] **Step 5: Add `ProviderConfig` to remaining providers**

`src/workbench/providers/source/email_gmail.py` — add `class ProviderConfig(BaseModel): google_api_script: str = ""`
`src/workbench/providers/enrichment/stub.py` — add `class ProviderConfig(BaseModel): pass`
`src/workbench/memory/noop.py` — add `class ProviderConfig(BaseModel): pass`

Each provider's `__init__` should accept `config: ProviderConfig` (or no args for providers with empty config).

- [ ] **Step 6: Run existing provider tests**

```bash
python -m pytest tests/test_claude_provider.py tests/test_google_chat.py tests/test_memory.py -v
```

Fix any import or signature issues from the ProviderConfig changes. Tests may need to construct providers via `ProviderConfig` now instead of positional args.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/providers/ src/workbench/memory/ tests/ \
  && git commit -m "Add ProviderConfig + close() lifecycle, switch to async subprocess (ADR 0005, 0007)"
```

---

## Task 8: QueueScorer + Ingestion Worker

**Goal:** Implement the `QueueScorer` ABC and `LLMQueueScorer` (Haiku). Implement the `IngestionQueueWorker` that dequeues items and runs the pipeline.

**Files:**
- Create: `src/workbench/providers/queue_scorer/__init__.py`
- Create: `src/workbench/providers/queue_scorer/base.py`
- Create: `src/workbench/providers/queue_scorer/llm.py`
- Create: `src/workbench/pipeline/worker.py`
- Create: `tests/test_queue_scorer.py`
- Create: `tests/test_queue_worker.py`

- [ ] **Step 1: Write QueueScorer ABC**

```python
# src/workbench/providers/queue_scorer/base.py
from abc import ABC, abstractmethod
from typing import Any


class QueueScorer(ABC):
    @abstractmethod
    async def score_urgency(self, raw_text: str, urgency_signals: dict[str, Any]) -> int:
        """Score urgency 0-100. Higher = process sooner."""
        ...
    async def close(self) -> None: pass
```

```python
# src/workbench/providers/queue_scorer/__init__.py
```

- [ ] **Step 2: Write LLMQueueScorer**

```python
# src/workbench/providers/queue_scorer/llm.py
import json
import os
import ssl
import asyncio
import httpx
from pydantic import BaseModel
from anthropic import AsyncAnthropic
from workbench.providers.queue_scorer.base import QueueScorer

URGENCY_PROMPT = """Rate the urgency of processing this content on a scale of 0-100.
Higher = more urgent (needs immediate attention).
Lower = can wait (informational, low priority).

Consider these signals from the source system:
{signals}

Content (first 2000 chars):
{content}

Return only a JSON object: {{"urgency": <0-100>}}"""


class LLMQueueScorer(QueueScorer):
    class ProviderConfig(BaseModel):
        api_key: str
        base_url: str = "https://plugboard.x2p.facebook.net"
        model: str = "claude-haiku-4-5-20251001"

    def __init__(self, config: ProviderConfig):
        self.model = config.model
        user = os.environ.get("USER", "anshulverma")
        cert_path = f"/var/facebook/credentials/{user}/agent_x509/claude_code_{user}.pem"
        ca_path = "/var/facebook/rootcanal/ca.pem"
        self._http_client = None
        if os.path.exists(cert_path):
            ssl_ctx = ssl.create_default_context(cafile=ca_path)
            ssl_ctx.load_cert_chain(cert_path)
            self._http_client = httpx.AsyncClient(verify=ssl_ctx)
        self.client = AsyncAnthropic(
            api_key=config.api_key, base_url=config.base_url,
            http_client=self._http_client,
        )

    async def score_urgency(self, raw_text: str, urgency_signals: dict) -> int:
        signals_text = json.dumps(urgency_signals, indent=2) if urgency_signals else "None"
        prompt = URGENCY_PROMPT.format(signals=signals_text, content=raw_text[:2000])
        try:
            response = await self.client.messages.create(
                model=self.model, max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            return max(0, min(100, int(data["urgency"])))
        except Exception:
            return 50  # default to medium urgency on failure

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
```

- [ ] **Step 3: Write IngestionQueueWorker**

```python
# src/workbench/pipeline/worker.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from workbench.models import JobStatus, JobTrigger, PipelineJob, RawItem
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class IngestionQueueWorker:
    def __init__(self, stores: Stores, pipeline, concurrency: int = 2):
        self.stores = stores
        self.pipeline = pipeline
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Ingestion queue worker started (concurrency={self.concurrency})")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        # Recover any items stuck in 'processing' from an unclean shutdown
        recovered = await self.stores.ingestion_queue.recover_stuck()
        if recovered:
            logger.info(f"Recovered {recovered} stuck queue entries")

        while self._running:
            try:
                entries = await self.stores.ingestion_queue.dequeue(limit=self.concurrency)
                if not entries:
                    await asyncio.sleep(2)
                    continue

                tasks = [self._process_entry(entry) for entry in entries]
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
                await asyncio.sleep(5)

    async def _process_entry(self, entry):
        async with self._semaphore:
            try:
                raw_item = RawItem(
                    id=entry.source_id or entry.id,
                    source_type=entry.source_type,
                    source_label="",
                    raw_text=entry.raw_content,
                    urgency_signals=entry.urgency_signals,
                )

                # Update the job status
                job = await self.stores.jobs.get_job(entry.job_id)
                if job and job.status.value == "queued":
                    job.status = JobStatus.RUNNING
                    await self.stores.jobs.update_job(job)

                await self.pipeline.process_raw_item(raw_item, entry.job_id)
                await self.stores.ingestion_queue.mark_completed(entry.id)

                # Mark job completed
                if job:
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)
                    await self.stores.jobs.update_job(job)

            except Exception as e:
                logger.error(f"Failed to process queue entry {entry.id}: {e}")
                await self.stores.ingestion_queue.mark_failed(entry.id, str(e))

                job = await self.stores.jobs.get_job(entry.job_id)
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    await self.stores.jobs.update_job(job)
```

- [ ] **Step 4: Write QueueScorer test**

```python
# tests/test_queue_scorer.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from workbench.providers.queue_scorer.llm import LLMQueueScorer


@pytest.mark.asyncio
async def test_llm_queue_scorer_parses_response():
    scorer = LLMQueueScorer.__new__(LLMQueueScorer)
    scorer.model = "test"
    scorer._http_client = None
    scorer.client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"urgency": 85}')]
    scorer.client.messages.create = AsyncMock(return_value=mock_resp)

    score = await scorer.score_urgency("urgent diff review needed", {"blocking_reviewer": True})
    assert score == 85


@pytest.mark.asyncio
async def test_llm_queue_scorer_clamps_to_range():
    scorer = LLMQueueScorer.__new__(LLMQueueScorer)
    scorer.model = "test"
    scorer._http_client = None
    scorer.client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"urgency": 150}')]
    scorer.client.messages.create = AsyncMock(return_value=mock_resp)

    score = await scorer.score_urgency("test", {})
    assert score == 100


@pytest.mark.asyncio
async def test_llm_queue_scorer_defaults_on_error():
    scorer = LLMQueueScorer.__new__(LLMQueueScorer)
    scorer.model = "test"
    scorer._http_client = None
    scorer.client = AsyncMock()
    scorer.client.messages.create = AsyncMock(side_effect=Exception("API error"))

    score = await scorer.score_urgency("test", {})
    assert score == 50
```

- [ ] **Step 5: Write worker test**

```python
# tests/test_queue_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workbench.pipeline.worker import IngestionQueueWorker
from workbench.models import IngestionQueueEntry, QueueEntryStatus, PipelineJob, JobStatus, JobTrigger


@pytest.mark.asyncio
async def test_worker_processes_entry(stores):
    # Create a job and queue entry
    job = PipelineJob(trigger=JobTrigger.MANUAL, status=JobStatus.QUEUED)
    await stores.jobs.save_job(job)

    entry = IngestionQueueEntry(
        raw_content="test content", source_type="manual",
        job_id=job.id, urgency_score=80,
    )
    await stores.ingestion_queue.enqueue(entry)

    mock_pipeline = AsyncMock()
    mock_pipeline.process_raw_item = AsyncMock()

    worker = IngestionQueueWorker(stores=stores, pipeline=mock_pipeline, concurrency=1)

    # Manually dequeue and process one entry
    entries = await stores.ingestion_queue.dequeue(limit=1)
    assert len(entries) == 1
    await worker._process_entry(entries[0])

    mock_pipeline.process_raw_item.assert_called_once()
    assert await stores.ingestion_queue.queue_depth() == 0
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_queue_scorer.py tests/test_queue_worker.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/workbench/providers/queue_scorer/ src/workbench/pipeline/worker.py \
  tests/test_queue_scorer.py tests/test_queue_worker.py \
  && git commit -m "Add QueueScorer (Haiku) and IngestionQueueWorker with retry/dead-letter (ADR 0007)"
```

---

## Task 9: Pipeline + API Refactor

**Goal:** Refactor the pipeline engine so `POST /api/process` enqueues into the ingestion queue instead of processing inline. Add queue API endpoints. Update `/health` with version, PG health, and queue stats.

**Files:**
- Modify: `src/workbench/pipeline/engine.py`
- Modify: `src/workbench/api/process.py`
- Modify: `src/workbench/api/health.py`
- Modify: `src/workbench/api/sources.py`
- Create: `src/workbench/api/queue.py`

- [ ] **Step 1: Refactor pipeline engine**

The pipeline engine gains a `process_raw_item()` method (called by the worker) and an `enqueue()` method (called by the API). The old `process()` method is removed.

```python
# src/workbench/pipeline/engine.py
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from workbench.memory.base import MemoryLayer
from workbench.models import (
    ExtractedItem, IngestionQueueEntry, Item, ItemOrigin, ItemStatus,
    JobStatus, JobTrigger, PipelineJob, Priority, RawItem,
)
from workbench.pipeline.enrichment import enrich_item
from workbench.pipeline.extraction import extract_items
from workbench.pipeline.filter import score_and_decide
from workbench.pipeline.triage import generate_card
from workbench.providers.enrichment.base import ContextEnricher
from workbench.providers.llm.base import LLMProvider
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class PipelineEngine:
    def __init__(self, stores: Stores, memory: MemoryLayer, llm: LLMProvider,
                 enricher: ContextEnricher, queue_scorer=None, triage_expiry_days: int = 7):
        self.stores = stores
        self.memory = memory
        self.llm = llm
        self.enricher = enricher
        self.queue_scorer = queue_scorer
        self.triage_expiry_days = triage_expiry_days

    async def enqueue(self, raw_text: str, source_type: str,
                      source_id: str | None = None,
                      urgency_signals: dict | None = None,
                      trigger: JobTrigger = JobTrigger.MANUAL) -> PipelineJob:
        """Enqueue content for processing. Returns the job (status=QUEUED)."""
        # Dedup check (skip for manual submissions)
        if source_id:
            if await self.stores.processed.is_processed(source_type, source_id):
                job = PipelineJob(trigger=trigger, status=JobStatus.COMPLETED,
                                  input_hash=hashlib.sha256(raw_text.encode()).hexdigest())
                await self.stores.jobs.save_job(job)
                return job

        # Create the job eagerly
        job = PipelineJob(
            trigger=trigger, status=JobStatus.QUEUED,
            input_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
        )
        await self.stores.jobs.save_job(job)

        # Score urgency inline
        urgency_score = 50
        if self.queue_scorer and urgency_signals:
            try:
                urgency_score = await self.queue_scorer.score_urgency(raw_text, urgency_signals)
            except Exception as e:
                logger.warning(f"Queue scorer failed, using default: {e}")

        # Enqueue
        entry = IngestionQueueEntry(
            raw_content=raw_text, source_type=source_type,
            source_id=source_id,
            urgency_signals=urgency_signals or {},
            urgency_score=urgency_score, job_id=job.id,
        )
        entry.max_attempts = 3
        await self.stores.ingestion_queue.enqueue(entry)

        # Mark as processed (for dedup on next poll)
        if source_id:
            await self.stores.processed.mark_processed(source_type, source_id)

        return job

    async def process_raw_item(self, raw_item: RawItem, job_id: str) -> None:
        """Process a single raw item through the pipeline. Called by the queue worker."""
        job = await self.stores.jobs.get_job(job_id)

        try:
            extracted = await extract_items(self.llm, raw_item.raw_text, raw_item.source_type)
            if job:
                job.items_extracted = len(extracted)
                await self.stores.jobs.update_job(job)

            for ext_item in extracted:
                ext_item = ExtractedItem(
                    summary=ext_item.summary, category=ext_item.category,
                    source_context=ext_item.source_context, raw_item=raw_item,
                )
                try:
                    await self._process_extracted_item(ext_item, job)
                except Exception as e:
                    logger.error(f"Failed to process extracted item: {e}")
                    if job:
                        job.items_failed += 1
                        await self.stores.jobs.update_job(job)
        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}")
            raise

    async def _process_extracted_item(self, ext_item: ExtractedItem, job: PipelineJob | None) -> None:
        action, relevance, confidence = await score_and_decide(
            self.llm, self.memory, self.stores.filter_rules, ext_item
        )

        if action == "auto_include":
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P2,
                status=ItemStatus.ACTIVE,
            )
            await self.stores.items.save_item(item)
            await self.memory.record_pipeline_decision(item, "auto_include", f"relevance={relevance}")
            if job:
                job.items_included += 1
                await self.stores.jobs.update_job(job)

        elif action == "auto_drop":
            await self.memory.record_pipeline_decision(
                Item(source_type=ext_item.raw_item.source_type, source_id=ext_item.raw_item.id,
                     summary=ext_item.summary, category=ext_item.category,
                     origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P3),
                "auto_drop", f"relevance={relevance}"
            )
            if job:
                job.items_dropped += 1
                await self.stores.jobs.update_job(job)

        else:
            # Create item with pending_triage status
            item = Item(
                source_type=ext_item.raw_item.source_type,
                source_id=ext_item.raw_item.id,
                summary=ext_item.summary, category=ext_item.category,
                origin=ItemOrigin.TRIAGED, priority=Priority.PENDING,
                status=ItemStatus.PENDING_TRIAGE,
            )
            await self.stores.items.save_item(item)

            enrichment = await enrich_item(self.enricher, ext_item)
            card = await generate_card(self.llm, ext_item, enrichment, ext_item.raw_item.source_type)
            card.item_id = item.id
            card.relevance_score = relevance
            card.confidence_score = confidence
            card.expires_at = datetime.now(timezone.utc) + timedelta(days=self.triage_expiry_days)
            await self.stores.triage.save_card(card)
            if job:
                job.items_triaged += 1
                await self.stores.jobs.update_job(job)
```

- [ ] **Step 2: Update `api/process.py` to enqueue**

```python
# src/workbench/api/process.py
from fastapi import APIRouter, Request
from pydantic import BaseModel
from workbench.models import JobTrigger

router = APIRouter(prefix="/api", tags=["process"])


class ProcessRequest(BaseModel):
    text: str
    source_type: str = "manual"


@router.post("/process")
async def process(req: ProcessRequest, request: Request):
    pipeline = request.app.state.pipeline
    job = await pipeline.enqueue(req.text, req.source_type, trigger=JobTrigger.MANUAL)
    return {"job_id": job.id, "status": job.status.value}
```

- [ ] **Step 3: Create `api/queue.py` for dead-letter endpoints**

```python
# src/workbench/api/queue.py
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("/dead-letter")
async def get_dead_letters(request: Request):
    stores = request.app.state.stores
    entries = await stores.ingestion_queue.get_dead_letters()
    return [e.model_dump() for e in entries]


@router.post("/dead-letter/{entry_id}/retry")
async def retry_dead_letter(entry_id: str, request: Request):
    stores = request.app.state.stores
    entries = await stores.ingestion_queue.get_dead_letters()
    if not any(e.id == entry_id for e in entries):
        raise HTTPException(404, "Dead letter entry not found")
    await stores.ingestion_queue.retry_dead_letter(entry_id)
    return {"status": "requeued"}


@router.delete("/dead-letter/{entry_id}")
async def purge_dead_letter(entry_id: str, request: Request):
    stores = request.app.state.stores
    await stores.ingestion_queue.purge_dead_letter(entry_id)
    return {"status": "purged"}
```

- [ ] **Step 4: Update `api/health.py`**

```python
# src/workbench/api/health.py
from fastapi import APIRouter, Request
from workbench import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    stores = request.app.state.stores
    result = {"status": "ok", "version": __version__}

    # PG health check
    try:
        depth = await stores.ingestion_queue.queue_depth()
        pending = await stores.triage.get_pending()
        dead = await stores.ingestion_queue.get_dead_letters()
        result["queue"] = {
            "ingestion_depth": depth,
            "triage_pending": len(pending),
            "dead_letters": len(dead),
        }
    except Exception:
        result["status"] = "degraded"
        result["error"] = "storage unavailable"

    return result
```

- [ ] **Step 5: Update `api/sources.py` — remove POST/DELETE**

```python
# src/workbench/api/sources.py
from fastapi import APIRouter, HTTPException, Request
from workbench.models import SourceConfigUpdate

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources")
async def list_sources(request: Request):
    stores = request.app.state.stores
    return await stores.sources.get_sources()


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, updates: SourceConfigUpdate, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return await stores.sources.update_source(source_id, updates)
```

- [ ] **Step 6: Update pipeline tests**

```python
# tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock
from workbench.pipeline.engine import PipelineEngine
from workbench.memory.noop import NoopMemoryLayer
from workbench.providers.enrichment.stub import StubEnricher
from workbench.models import (
    ExtractedItem, ItemCategory, RawItem, TriageCard, TriageOption,
    JobTrigger, JobStatus, ItemFilters, ItemStatus,
)


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
async def test_enqueue_creates_job(stores, mock_llm):
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())
    job = await engine.enqueue("test content", "manual")
    assert job.status == JobStatus.QUEUED

    fetched = await stores.jobs.get_job(job.id)
    assert fetched is not None
    assert await stores.ingestion_queue.queue_depth() == 1


@pytest.mark.asyncio
async def test_process_raw_item_auto_include(stores, mock_llm):
    mock_llm.score_relevance.return_value = (85, 90)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("diff content", "diff")
    raw = RawItem(id="D123_100", source_type="diff", source_label="D123", raw_text="diff content")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters())
    assert len(items) == 1
    assert items[0].status == ItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_process_raw_item_triage(stores, mock_llm):
    mock_llm.score_relevance.return_value = (50, 50)
    engine = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, StubEnricher())

    job = await engine.enqueue("ambiguous content", "email")
    raw = RawItem(id="E1", source_type="email", source_label="email", raw_text="ambiguous content")
    await engine.process_raw_item(raw, job.id)

    items = await stores.items.get_items(ItemFilters(status=ItemStatus.PENDING_TRIAGE))
    assert len(items) == 1
    pending = await stores.triage.get_pending()
    assert len(pending) == 1
    assert pending[0].item_id == items[0].id
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_pipeline.py -v
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/workbench/pipeline/engine.py src/workbench/api/ tests/test_pipeline.py \
  && git commit -m "Refactor pipeline for queue-based processing, add dead-letter API (ADR 0007)"
```

---

## Task 10: Scheduler + Triage Queue

**Goal:** Update the scheduler to use persistent triage queue state (`bot_message_id` from DB), daily cap, card expiry, and a richer morning briefing.

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Modify: `src/workbench/api/triage.py`

- [ ] **Step 1: Rewrite scheduler for persistent triage state**

```python
# src/workbench/pipeline/scheduler.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from workbench.config import AppConfig
from workbench.memory.base import MemoryLayer
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, Priority, TriageResponse,
)
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.triage import format_card_for_chat
from workbench.providers.messenger.base import Messenger
from workbench.storage.base import Stores

logger = logging.getLogger(__name__)


class WorkbenchScheduler:
    def __init__(self, stores: Stores, memory: MemoryLayer, pipeline: PipelineEngine,
                 messenger: Messenger | None, config: AppConfig):
        self.stores = stores
        self.memory = memory
        self.pipeline = pipeline
        self.messenger = messenger
        self.config = config
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.add_job(
            self._manage_triage_queue, "interval", seconds=30, id="triage_queue"
        )
        self.scheduler.add_job(
            self._morning_briefing, "cron",
            hour=self.config.scheduler.morning_briefing_hour, id="briefing"
        )
        self.scheduler.add_job(
            self._expire_cards, "cron", hour=3, id="expire_cards"
        )
        self.scheduler.start()

    async def _manage_triage_queue(self):
        if not self.messenger:
            return

        # Check daily cap
        sent_today = await self.stores.triage.count_sent_today()
        if sent_today >= self.config.triage.daily_cap:
            return

        pending = await self.stores.triage.get_pending()
        if not pending:
            return

        # Find the currently sent card (awaiting response)
        sent_cards = [c for c in pending if c.status == "sent"]
        if sent_cards:
            card = sent_cards[0]
            responses = await self.messenger.poll_responses(card.bot_message_id)
            for resp in responses:
                text = resp.get("text", "").strip().lower()
                if text in ("skip all", "skip remaining"):
                    for c in pending:
                        if c.responded_at is None:
                            await self.stores.triage.record_response(
                                c.id, TriageResponse(card_id=c.id, choice=0, raw_text="skip all")
                            )
                    return
                try:
                    choice = int(text)
                    if 1 <= choice <= len(card.options):
                        await self._handle_triage_response(card, choice)
                        return
                except ValueError:
                    pass
            return

        # Send the next unsent card
        card = await self.stores.triage.get_next_unsent()
        if not card:
            return

        text = format_card_for_chat(card, position=1, total=len(pending))
        msg_id = await self.messenger.send_card(text)
        card.status = "sent"
        card.sent_at = datetime.now(timezone.utc)
        card.bot_message_id = msg_id
        card.daily_sequence = sent_today + 1
        await self.stores.triage.update_card(card)

    async def _handle_triage_response(self, card, choice: int):
        option = card.options[choice - 1]
        response = TriageResponse(card_id=card.id, choice=choice)
        await self.stores.triage.record_response(card.id, response)

        if option.action == "add_todo":
            priority = Priority(option.details.get("priority", "P2"))
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
                )
            else:
                item = Item(
                    source_type=card.card_content.get("source_type", "unknown"),
                    source_id=card.id,
                    summary=card.card_content.get("summary", ""),
                    category=ItemCategory.ACTION_ITEM,
                    origin=ItemOrigin.TRIAGED, priority=priority,
                    status=ItemStatus.ACTIVE,
                )
                await self.stores.items.save_item(item)

        elif option.action == "skip":
            if card.item_id:
                await self.stores.items.update_item(
                    card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
                )

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

        # Send confirmation
        if self.messenger:
            await self.messenger.send_card(f"Got it — {option.label}")

    async def _expire_cards(self):
        expired = await self.stores.triage.expire_old_cards(self.config.triage.expiry_days)
        if expired:
            logger.info(f"Auto-expired {expired} triage cards")

    async def _morning_briefing(self):
        if not self.messenger:
            return
        from workbench.models import ItemFilters
        items = await self.stores.items.get_items(ItemFilters(status=ItemStatus.ACTIVE))
        pending = await self.stores.triage.get_pending()
        queue_depth = await self.stores.ingestion_queue.queue_depth()
        dead_letters = await self.stores.ingestion_queue.get_dead_letters()

        p0 = [i for i in items if i.priority == Priority.P0]
        p1 = [i for i in items if i.priority == Priority.P1]

        lines = ["*Morning Briefing*", ""]

        if p0:
            lines.append(f"*P0 — Today ({len(p0)}):*")
            for i in p0:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        if p1:
            lines.append(f"*P1 — This Week ({len(p1)}):*")
            for i in p1:
                lines.append(f"  • {i.summary} [{i.source_type}]")

        if pending:
            oldest = min(c.sent_at or c.expires_at or datetime.now(timezone.utc) for c in pending)
            age_days = (datetime.now(timezone.utc) - oldest).days
            lines.append(f"\n*Pending triage:* {len(pending)} cards (oldest: {age_days}d)")

        if queue_depth > 0 or dead_letters:
            lines.append(f"\n*Queue health:* {queue_depth} queued")
            if dead_letters:
                lines.append(f"  ⚠ {len(dead_letters)} dead-letter entries need investigation")

        if not p0 and not p1 and not pending:
            lines.append("All clear! No P0/P1 items, no pending triage.")

        await self.messenger.send_card("\n".join(lines))
```

- [ ] **Step 2: Update `api/triage.py` for item status transitions**

```python
# src/workbench/api/triage.py
from fastapi import APIRouter, HTTPException, Request
from workbench.models import (
    FilterRule, InteractionEntry, Item, ItemCategory, ItemOrigin,
    ItemStatus, ItemUpdate, Priority, TriageResponse,
)

router = APIRouter(prefix="/api", tags=["triage"])


@router.get("/triage/pending")
async def get_pending(request: Request):
    stores = request.app.state.stores
    return await stores.triage.get_pending()


@router.post("/triage/respond")
async def respond_to_triage(response: TriageResponse, request: Request):
    stores = request.app.state.stores
    memory = request.app.state.memory
    card = await stores.triage.get_card(response.card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")
    if response.choice < 1 or response.choice > len(card.options):
        raise HTTPException(400, f"Invalid choice {response.choice}, must be 1-{len(card.options)}")

    option = card.options[response.choice - 1]
    await stores.triage.record_response(response.card_id, response)

    if option.action == "add_todo":
        priority = Priority(option.details.get("priority", "P2"))
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(priority=priority, status=ItemStatus.ACTIVE)
            )
        else:
            item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=card.id,
                summary=card.card_content.get("summary", ""),
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED, priority=priority,
            )
            await stores.items.save_item(item)

    elif option.action == "skip":
        if card.item_id:
            await stores.items.update_item(
                card.item_id, ItemUpdate(status=ItemStatus.ARCHIVED)
            )

    elif option.action == "mute_pattern":
        rule = FilterRule(
            source_type=card.card_content.get("source_type"),
            pattern=card.card_content.get("summary", ""),
            action="drop",
            created_from_interaction_id=card.id,
        )
        await stores.filter_rules.add_rule(rule)

    entry = InteractionEntry(
        source_type=card.card_content.get("source_type", "unknown"),
        item_summary=card.card_content.get("summary", ""),
        triage_card_full=card.card_content,
        options_presented=[o.model_dump() for o in card.options],
        option_chosen=option.label,
    )
    await stores.interactions.append(entry)
    await memory.record_triage(card, response)

    return {"status": "recorded", "action": option.action}
```

- [ ] **Step 3: Commit**

```bash
git add src/workbench/pipeline/scheduler.py src/workbench/api/triage.py \
  src/workbench/api/sources.py \
  && git commit -m "Update scheduler with persistent triage queue, daily cap, morning briefing"
```

---

## Task 11: End-to-End Verification

**Goal:** Build the full stack, run it, and verify the complete triage loop works.

**Files:**
- Modify: `src/workbench/main.py` (uncomment worker + queue router)

- [ ] **Step 1: Ensure main.py is fully wired**

Uncomment or add the worker, queue router, and queue scorer references that were deferred from Task 4. The `main.py` from Task 4 Step 8 should now be complete with all imports and wiring.

- [ ] **Step 2: Copy config.example.yml to config.yml and configure**

```bash
cp config.example.yml config.yml
```

Edit `config.yml` with real values for `ANTHROPIC_API_KEY`, `GCHAT_SPACE_ID`, etc. (these should be in environment variables already).

- [ ] **Step 3: Build and start the full stack**

```bash
podman compose build
podman compose up -d
podman compose logs -f workbench 2>&1 | head -30
```

Expected: Alembic migration runs, server starts on port 8421.

- [ ] **Step 4: Verify health**

```bash
curl http://localhost:8421/health
```

Expected: `{"status":"ok","version":"0.1.0","queue":{"ingestion_depth":0,"triage_pending":0,"dead_letters":0}}`

- [ ] **Step 5: Test manual processing**

```bash
curl -X POST http://localhost:8421/api/process \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"text": "Meeting with Alice: discussed auth migration. Action items: 1) Write design doc by Friday 2) Set up test environment", "source_type": "meeting"}'
```

Expected: Returns `{"job_id": "...", "status": "queued"}`. The job is enqueued, not processed inline.

Wait a few seconds for the worker to process it:

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/items
```

Expected: Extracted items appear (either auto-included or pending triage).

- [ ] **Step 6: Test triage response (if Google Chat is configured)**

If `GCHAT_SPACE_ID` is set, verify a triage card was sent to Google Chat. Reply with "1" in the chat. Then:

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/items?status=active
```

Expected: The item appears with the selected priority.

- [ ] **Step 7: Test queue health**

```bash
curl http://localhost:8421/health
```

Expected: Queue stats reflect the processing that happened.

- [ ] **Step 8: Test filter rule creation**

```bash
curl -X POST http://localhost:8421/api/filter-rules \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"pattern": "CI bot comments on diffs", "action": "drop"}'
```

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/filter-rules
```

Expected: The filter rule is stored and returned.

- [ ] **Step 9: Test dead-letter endpoint**

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8421/api/queue/dead-letter
```

Expected: Empty list `[]` (no failures yet).

- [ ] **Step 10: Run the full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 11: Move the old Phase 1a plan to stale**

```bash
mv docs/plans/2026-05-27-phase-1a-core-triage-loop.md docs/plans/_stale/
```

- [ ] **Step 12: Commit**

```bash
git add -A && git commit -m "Phase 1a migration complete: PG storage, YAML config, durable queues, provider registry"
```

---

## What's Next

After Phase 1a migration is verified end-to-end:

- **Phase 1b**: Stand up Zep via Podman, implement `ZepMemoryLayer`, wire preferences
- **Phase 1c**: Wire entity knowledge into enrichment
- **Phase 1d**: Wire relationship context into triage card generation
- **Internal/External Split**: Create `workbench-meta` repo, move Meta-specific providers, add Discord/GitHub external defaults, genericize docs, push to GitHub
