# Workbench Management Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the Management Dashboard — a same-origin React SPA at `/ui` over `/api` — together with its backing Stats Endpoint, `ingestion_runs` table, per-source Source Job scheduler with `source_id`-keyed Watermark, source CRUD via Config Write-Back + Targeted Hot-Reload, messenger info/edit, Fact Curation, and web triage respond/confirm.

**Architecture:** A React 19 + Vite 7 HashRouter SPA loads from the static `/ui` mount, fetches a bearer token from the Token-Vending Endpoint, and drives all reads/writes through `/api` via TanStack Query. Read paths fan out to repository `COUNT ... GROUP BY` aggregation methods and the new `IngestionRunStore`; write paths run Config Write-Back (ruamel round-trip on `config.yml`) then Targeted Hot-Reload (validate -> instantiate -> write -> swap under an `asyncio.Lock`), reflecting source/messenger changes without a restart. One APScheduler `CronTrigger` Source Job runs per enabled source through the shared `_poll_one_source`, which records each poll as an Ingestion Run.

**Tech Stack:** React 19, Vite 7, Tailwind v4 (`@tailwindcss/vite`, CSS-first), shadcn/ui, react-router 7 `HashRouter`, TanStack Query v5, Recharts 3, Zod 4, react-hook-form 7, openapi-typescript 7, vitest 3, @testing-library/react 16, msw 2, sonner, tw-animate-css; backend FastAPI / asyncpg / Alembic / APScheduler / ruamel.yaml.

**Test commands:**
- Backend all: `python -m pytest tests/ -v --tb=short`
- Backend single: `python -m pytest tests/test_NAME.py::test_FUNC -v`
- Migrations: `alembic upgrade head`
- Frontend all: `cd ui && npm run test` (vitest, to be added)
- Frontend single: `cd ui && npx vitest run src/path/file.test.tsx`
- Regenerate API types: `cd ui && npm run gen:api`

---

## File Structure

### Backend — new files
| File | Responsibility |
| --- | --- |
| `src/workbench/redaction.py` | Shared `redact_secrets()` Redaction Rule (key-name denylist + field denylist). |
| `src/workbench/storage/ingestion_runs.py` | `IngestionRunStore` ABC + `PgIngestionRunStore`. |
| `src/workbench/config_writer.py` | ruamel.yaml Config Write-Back (edit `sources:`/`messenger:` nodes only, atomic). |
| `src/workbench/api/stats.py` | `GET /api/stats/{overview,sources,queue,ingestion-timeseries}`. |
| `src/workbench/api/activity.py` | `GET /api/activity`. |
| `src/workbench/api/messenger.py` | `GET/PATCH /api/messenger`. |
| `src/workbench/api/connections.py` | `GET /api/connections`. |
| `src/workbench/migrations/versions/004_stats_indexes.py` | items/ingestion_queue indexes. |
| `src/workbench/migrations/versions/005_ingestion_runs.py` | `ingestion_runs` table + index. |

### Backend — modified files
| File | Change |
| --- | --- |
| `src/workbench/storage/base.py` | New count/list methods on Item/IngestionQueue/Job stores; add `IngestionRunStore` to `Stores`; `count_dead_letters`. |
| `src/workbench/storage/postgres/{items,ingestion_queue,jobs}.py` | Implement new aggregation methods. |
| `src/workbench/storage/postgres/stores.py` | Wire `PgIngestionRunStore`. |
| `src/workbench/models.py` | `Fact.id`, `Fact.timestamp: datetime | None`; new `IngestionRun` model. |
| `src/workbench/config.py` | `RetentionConfig.ingestion_runs_days`; config `version` bump to `0.4.0`. |
| `src/workbench/api/health.py` | Use `queue_depth()` + `count_dead_letters()`. |
| `src/workbench/api/jobs.py` | `GET /api/jobs` list with `limit/offset/status` + `total`. |
| `src/workbench/api/sources.py` | POST/PATCH(full)/DELETE/poll/adapter-types; allowlist + write-back + hot-reload. |
| `src/workbench/api/memory.py` | Envelope response; DELETE/PATCH curation. |
| `src/workbench/api/triage.py` | 409 guard; `POST /api/triage/confirm`; audit-gap fix. |
| `src/workbench/api/debug.py` | Import `redact_secrets` from `redaction.py`; keep `/api/debug/config`. |
| `src/workbench/pipeline/scheduler.py` | `_poll_one_source`; per-source Source Jobs; watermark by `source_id`; Ingestion Run hooks; runtime job mgmt; messenger rebind helper. |
| `src/workbench/memory/{base,noop,http}.py` | `delete_fact`/`update_fact`/`list_facts`; fix `timestamp` population. |
| `src/workbench/main.py` | Register new routers; `app.state.reload_lock`; loopback bind. |

### Frontend — new files
`ui/components.json`, `ui/vitest.config.ts`, `ui/src/test/setup.ts`, `ui/src/test/server.ts` (MSW), `ui/src/lib/{query-client,format,api-types}.ts`, `ui/src/hooks/*.ts`, `ui/src/components/{AppShell,AppSidebar,ErrorBoundary,EmptyState,StatCard,DataTable,ChartCard,HealthBadge,SourceForm,FactRow}.tsx`, `ui/src/components/ui/*` (shadcn), `ui/src/pages/{Overview,Triage,Ingestion,Sources,Knowledge,Messenger,Settings}.tsx`.

### Frontend — modified files
`ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/src/index.css`, `ui/src/main.tsx`, `ui/src/App.tsx`, move `ui/src/api.ts` -> `ui/src/lib/api.ts`; delete `ui/tailwind.config.js`, `ui/postcss.config.js`.

---

## PHASE A — Backend foundation

### Task A1: Promote `redact_secrets()` to `workbench/redaction.py`
**Files:**
- Create `src/workbench/redaction.py`
- Modify `src/workbench/api/debug.py`
- Test `tests/test_redaction.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_redaction.py
import pytest
from workbench.redaction import redact_secrets, REDACTED


@pytest.mark.parametrize("key", [
    "api_token", "API_KEY", "client_secret", "db_password",
    "postgres_dsn", "google_credential", "service_account_key_path",
])
def test_redacts_secret_key_names(key):
    out = redact_secrets({key: "supersecret-value"})
    assert out[key] == REDACTED
    assert "supersecret-value" not in str(out)


def test_keeps_safe_keys():
    out = redact_secrets({"space_id": "spaces/AAA", "timeout_seconds": 5})
    assert out == {"space_id": "spaces/AAA", "timeout_seconds": 5}


def test_recurses_nested_dicts_and_lists():
    raw = {
        "server": {"api_token": "T", "port": 8421},
        "sources": [{"adapter_type": "github", "config": {"token": "X"}}],
    }
    out = redact_secrets(raw)
    assert out["server"]["api_token"] == REDACTED
    assert out["server"]["port"] == 8421
    assert out["sources"][0]["config"]["token"] == REDACTED
    assert out["sources"][0]["adapter_type"] == "github"
    assert "T" not in str(out) and "X" not in str(out)


def test_explicit_field_denylist():
    out = redact_secrets({"service_account_key_path": "/etc/sa.json"})
    assert out["service_account_key_path"] == REDACTED


def test_depth_guard_returns_marker():
    deep = cur = {}
    for _ in range(15):
        cur["nested"] = {}
        cur = cur["nested"]
    out = redact_secrets(deep)
    assert "..." in str(out)
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_redaction.py -v`
Expected: `ModuleNotFoundError: No module named 'workbench.redaction'`

- [ ] Step 3: Write minimal implementation

```python
# src/workbench/redaction.py
from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Key-name denylist regex (the Redaction Rule).
SECRET_PATTERN = re.compile(
    r"(token|key|secret|password|dsn|credential|service_account)",
    re.IGNORECASE,
)

# Explicit field denylist (exact key names that must always be redacted).
FIELD_DENYLIST = {
    "service_account_key_path",
    "postgres_dsn",
    "api_token",
}


def _is_secret_key(key: str) -> bool:
    return key in FIELD_DENYLIST or bool(SECRET_PATTERN.search(key))


def redact_secrets(obj: Any, depth: int = 0) -> Any:
    """Recursively redact secret-bearing keys from config-derived data."""
    if depth > 10:
        return "..."
    if isinstance(obj, dict):
        return {
            k: REDACTED if _is_secret_key(str(k)) else redact_secrets(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(i, depth + 1) for i in obj]
    return obj
```

Then update `src/workbench/api/debug.py` to delegate (replace the local `SECRET_PATTERN`/`_redact_secrets` definitions):

```python
# src/workbench/api/debug.py  (top imports + removal of local copy)
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from workbench.redaction import redact_secrets as _redact_secrets

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/debug", tags=["debug"])
```

Delete the old `SECRET_PATTERN = ...` and `def _redact_secrets(...)` block (lines 12–25 of the original file). All existing call sites (`debug_config`) keep using `_redact_secrets`.

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_redaction.py tests/test_debug_endpoints.py -v`
Expected: PASS (all redaction tests + existing `test_debug_config_redacts_secrets`)

- [ ] Step 5: Commit
`git commit -am "feat(redaction): promote redact_secrets to workbench/redaction.py with field denylist"`

---

### Task A2: Fix /health depth bug + `count_dead_letters()`
**Files:**
- Modify `src/workbench/storage/base.py`
- Modify `src/workbench/storage/postgres/ingestion_queue.py`
- Modify `src/workbench/api/health.py`
- Modify `tests/test_debug_endpoints.py` (the `_make_app` stub used `get_depth`)
- Test `tests/test_health_counts.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_health_counts.py
import pytest
from workbench.models import IngestionQueueEntry, QueueEntryStatus


async def _enqueue(stores, status, n):
    for i in range(n):
        e = IngestionQueueEntry(
            raw_content=f"c{i}", source_type="github", job_id=f"j-{status}-{i}",
            status=QueueEntryStatus(status),
        )
        await stores.ingestion_queue.enqueue(e)


@pytest.mark.asyncio
async def test_count_dead_letters_uses_count(stores):
    await _enqueue(stores, "dead_letter", 3)
    await _enqueue(stores, "queued", 2)
    assert await stores.ingestion_queue.count_dead_letters() == 3


@pytest.mark.asyncio
async def test_health_uses_queue_depth_and_count(client, app_with_state):
    stores = app_with_state.state.stores
    await _enqueue(stores, "dead_letter", 2)
    await _enqueue(stores, "queued", 1)
    r = await client.get("/health")
    assert r.status_code == 200
    q = r.json()["queue"]
    assert q["ingestion_depth"] == 1   # queued+processing only
    assert q["dead_letters"] == 2
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_health_counts.py -v`
Expected: `AttributeError: ... has no attribute 'count_dead_letters'` (first test); second test fails with `AttributeError: ... 'get_depth'` raised inside `/health`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/storage/base.py`, add to `IngestionQueueStore` (after `queue_depth`):

```python
    @abstractmethod
    async def count_dead_letters(self) -> int:
        """COUNT of dead_letter rows (never a full-row scan)."""
        ...
```

In `src/workbench/storage/postgres/ingestion_queue.py`, add after `queue_depth`:

```python
    async def count_dead_letters(self) -> int:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM ingestion_queue WHERE status = 'dead_letter'"
        )
        return row["cnt"]  # type: ignore[index]
```

In `src/workbench/api/health.py`, replace the `if critical_healthy:` block body:

```python
    queue_stats = {}
    if critical_healthy:
        try:
            depth = await stores.ingestion_queue.queue_depth()
            pending = await stores.triage.get_pending()
            dead = await stores.ingestion_queue.count_dead_letters()
            queue_stats = {
                "ingestion_depth": depth,
                "triage_pending": len(pending),
                "dead_letters": dead,
            }
        except Exception:
            pass
```

In `tests/test_debug_endpoints.py`, update the stub so it does not reference the removed `get_depth`:

```python
    stores.ingestion_queue.queue_depth = AsyncMock(return_value=0)
    stores.ingestion_queue.count_dead_letters = AsyncMock(return_value=0)
```

(Replace the existing `stores.ingestion_queue.get_depth = AsyncMock(return_value=0)` line.)

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_health_counts.py tests/test_api.py tests/test_debug_endpoints.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "fix(health): standardize on queue_depth() + add count_dead_letters() COUNT"`

---

### Task A3: Aggregation store methods + stats indexes migration
**Files:**
- Modify `src/workbench/storage/base.py`
- Modify `src/workbench/storage/postgres/{items,ingestion_queue,jobs}.py`
- Create `src/workbench/migrations/versions/004_stats_indexes.py`
- Test `tests/test_aggregations.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_aggregations.py
import pytest
from workbench.models import (
    Item, ItemCategory, ItemOrigin, ItemStatus, Priority,
    IngestionQueueEntry, QueueEntryStatus, PipelineJob, JobTrigger, JobStatus,
)


def _item(source, status, priority, category):
    return Item(
        source_type=source, source_id="x", summary="s",
        category=category, origin=ItemOrigin.TRIAGED,
        priority=priority, status=status,
    )


@pytest.mark.asyncio
async def test_item_count_by_status(stores):
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING))
    await stores.items.save_item(_item("email", ItemStatus.ARCHIVED, Priority.P2, ItemCategory.INFORMATIONAL))
    assert await stores.items.count_by_status() == {"active": 2, "archived": 1}


@pytest.mark.asyncio
async def test_item_count_by_priority(stores):
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    assert await stores.items.count_by_priority() == {"P0": 2}


@pytest.mark.asyncio
async def test_item_count_by_category(stores):
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    await stores.items.save_item(_item("email", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING))
    assert await stores.items.count_by_category() == {"action_item": 1, "meeting": 1}


@pytest.mark.asyncio
async def test_item_count_by_source(stores):
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P1, ItemCategory.MEETING))
    await stores.items.save_item(_item("email", ItemStatus.ACTIVE, Priority.P2, ItemCategory.INFORMATIONAL))
    assert await stores.items.count_by_source() == {"github": 2, "email": 1}


@pytest.mark.asyncio
async def test_queue_count_by_status_and_source(stores):
    for st, src in [("queued", "github"), ("processing", "github"), ("dead_letter", "email")]:
        await stores.ingestion_queue.enqueue(IngestionQueueEntry(
            raw_content="c", source_type=src, job_id=f"j-{st}", status=QueueEntryStatus(st),
        ))
    assert await stores.ingestion_queue.count_by_status() == {
        "queued": 1, "processing": 1, "dead_letter": 1,
    }
    # raw_enqueued+in_flight = queued+processing only (excludes dead_letter/completed)
    assert await stores.ingestion_queue.count_by_source() == {"github": 2}


@pytest.mark.asyncio
async def test_job_list_and_count(stores):
    for i in range(3):
        await stores.jobs.save_job(PipelineJob(
            trigger=JobTrigger.MANUAL, status=JobStatus.COMPLETED, input_hash=f"h{i}",
        ))
    await stores.jobs.save_job(PipelineJob(
        trigger=JobTrigger.POLL, status=JobStatus.FAILED, input_hash="hf",
    ))
    assert await stores.jobs.count() == 4
    assert await stores.jobs.count(status="failed") == 1
    page = await stores.jobs.list_jobs(limit=2, offset=0)
    assert len(page) == 2
    completed = await stores.jobs.list_jobs(limit=10, offset=0, status="completed")
    assert len(completed) == 3
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_aggregations.py -v`
Expected: `AttributeError: 'PgItemStore' object has no attribute 'count_by_status'`

- [ ] Step 3: Write minimal implementation

In `src/workbench/storage/base.py`, add to `ItemStore`:

```python
    @abstractmethod
    async def count_by_status(self) -> dict[str, int]: ...
    @abstractmethod
    async def count_by_priority(self) -> dict[str, int]: ...
    @abstractmethod
    async def count_by_category(self) -> dict[str, int]: ...
    @abstractmethod
    async def count_by_source(self) -> dict[str, int]: ...
```

Add to `IngestionQueueStore` (after `count_dead_letters`):

```python
    @abstractmethod
    async def count_by_status(self) -> dict[str, int]: ...
    @abstractmethod
    async def count_by_source(self) -> dict[str, int]: ...
```

Add to `JobStore`:

```python
    @abstractmethod
    async def list_jobs(self, limit: int, offset: int, status: str | None = None) -> list[PipelineJob]: ...
    @abstractmethod
    async def count(self, status: str | None = None) -> int: ...
```

In `src/workbench/storage/postgres/items.py`, add (before `_row_to_item`):

```python
    async def _count_group(self, column: str) -> dict[str, int]:
        rows = await self.pool.fetch(
            f"SELECT {column} AS k, COUNT(*) AS cnt FROM items GROUP BY {column}"
        )
        return {r["k"]: r["cnt"] for r in rows}

    async def count_by_status(self) -> dict[str, int]:
        return await self._count_group("status")

    async def count_by_priority(self) -> dict[str, int]:
        return await self._count_group("priority")

    async def count_by_category(self) -> dict[str, int]:
        return await self._count_group("category")

    async def count_by_source(self) -> dict[str, int]:
        return await self._count_group("source_type")
```

In `src/workbench/storage/postgres/ingestion_queue.py`, add (after `count_dead_letters`):

```python
    async def count_by_status(self) -> dict[str, int]:
        rows = await self.pool.fetch(
            "SELECT status AS k, COUNT(*) AS cnt FROM ingestion_queue GROUP BY status"
        )
        return {r["k"]: r["cnt"] for r in rows}

    async def count_by_source(self) -> dict[str, int]:
        rows = await self.pool.fetch(
            "SELECT source_type AS k, COUNT(*) AS cnt FROM ingestion_queue "
            "WHERE status IN ('queued', 'processing') GROUP BY source_type"
        )
        return {r["k"]: r["cnt"] for r in rows}
```

In `src/workbench/storage/postgres/jobs.py`, add (after `update_job`):

```python
    async def list_jobs(self, limit: int, offset: int, status: str | None = None) -> list[PipelineJob]:
        if status:
            rows = await self.pool.fetch(
                "SELECT * FROM jobs WHERE status = $1 ORDER BY created_at DESC "
                "LIMIT $2 OFFSET $3",
                status, limit, offset,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
        return [self._row_to_job(r) for r in rows]

    async def count(self, status: str | None = None) -> int:
        if status:
            row = await self.pool.fetchrow(
                "SELECT COUNT(*) AS cnt FROM jobs WHERE status = $1", status
            )
        else:
            row = await self.pool.fetchrow("SELECT COUNT(*) AS cnt FROM jobs")
        return row["cnt"]  # type: ignore[index]
```

Create the index migration:

```python
# src/workbench/migrations/versions/004_stats_indexes.py
"""stats indexes: items(source_type,status), ingestion_queue(status).

Revision ID: 004
Revises: 003
Create Date: 2026-06-05
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_items_source_status", "items", ["source_type", "status"])
    op.create_index("ix_ingestion_queue_status", "ingestion_queue", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_queue_status", "ingestion_queue")
    op.drop_index("ix_items_source_status", "items")
```

- [ ] Step 4: Run test to verify it passes
Run: `alembic upgrade head && python -m pytest tests/test_aggregations.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(storage): COUNT-by aggregation methods + jobs list/count + stats indexes"`

---

### Task A4: Stats + activity + jobs-list endpoints
**Files:**
- Create `src/workbench/api/stats.py`
- Create `src/workbench/api/activity.py`
- Modify `src/workbench/api/jobs.py`
- Modify `src/workbench/main.py` (register routers)
- Test `tests/test_stats_api.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_stats_api.py
import pytest
from workbench.models import (
    Item, ItemCategory, ItemOrigin, ItemStatus, Priority,
    IngestionQueueEntry, QueueEntryStatus, PipelineJob, JobTrigger, JobStatus,
)


def _item(source, status, priority, category):
    return Item(
        source_type=source, source_id="x", summary="s",
        category=category, origin=ItemOrigin.TRIAGED, priority=priority, status=status,
    )


@pytest.mark.asyncio
async def test_stats_overview_returns_six_counts(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    await stores.ingestion_queue.enqueue(IngestionQueueEntry(
        raw_content="c", source_type="github", job_id="j1", status=QueueEntryStatus.PROCESSING,
    ))
    await stores.ingestion_queue.enqueue(IngestionQueueEntry(
        raw_content="c", source_type="github", job_id="j2", status=QueueEntryStatus.DEAD_LETTER,
    ))
    r = await client.get("/api/stats/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["pending_triage"] == 0
    assert data["in_flight"] == 1
    assert data["dead_letters"] == 1
    assert data["active_items"] == 1
    assert data["sources_enabled"] == 0
    assert data["sources_total"] == 0
    assert data["items"]["by_priority"]["P0"] == 1
    assert data["items"]["by_category"]["action_item"] == 1
    assert data["items"]["by_source"]["github"] == 1


@pytest.mark.asyncio
async def test_stats_overview_requires_auth(client, app_with_state):
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/stats/overview")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_stats_queue(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.ingestion_queue.enqueue(IngestionQueueEntry(
        raw_content="c", source_type="github", job_id="j1", status=QueueEntryStatus.QUEUED,
    ))
    r = await client.get("/api/stats/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] == 1
    assert data["processing"] == 0
    assert data["dead_letter"] == 0


@pytest.mark.asyncio
async def test_jobs_list_with_total(client, app_with_state):
    stores = app_with_state.state.stores
    for i in range(3):
        await stores.jobs.save_job(PipelineJob(
            trigger=JobTrigger.MANUAL, status=JobStatus.COMPLETED, input_hash=f"h{i}",
        ))
    r = await client.get("/api/jobs?limit=2&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["jobs"]) == 2


@pytest.mark.asyncio
async def test_activity_returns_recent_items(client, app_with_state):
    stores = app_with_state.state.stores
    await stores.items.save_item(_item("github", ItemStatus.ACTIVE, Priority.P0, ItemCategory.ACTION_ITEM))
    r = await client.get("/api/activity?limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["source_type"] == "github"
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_stats_api.py -v`
Expected: 404 on `/api/stats/overview` (router not registered)

- [ ] Step 3: Write minimal implementation

```python
# src/workbench/api/stats.py
from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
async def overview(request: Request):
    stores = request.app.state.stores
    by_status = await stores.items.count_by_status()
    by_priority = await stores.items.count_by_priority()
    by_category = await stores.items.count_by_category()
    by_source = await stores.items.count_by_source()
    pending = await stores.triage.get_pending()
    in_flight = await stores.ingestion_queue.queue_depth()
    dead = await stores.ingestion_queue.count_dead_letters()
    sources = getattr(request.app.state, "sources", [])
    db_sources = await stores.sources.get_sources()
    enabled = sum(1 for s in db_sources if s.enabled)
    return {
        "pending_triage": len(pending),
        "in_flight": in_flight,
        "dead_letters": dead,
        "active_items": by_status.get("active", 0),
        "sources_enabled": enabled,
        "sources_total": len(db_sources),
        "items": {
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_source": by_source,
        },
    }


@router.get("/queue")
async def queue(request: Request):
    stores = request.app.state.stores
    by_status = await stores.ingestion_queue.count_by_status()
    return {
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "dead_letter": by_status.get("dead_letter", 0),
    }


@router.get("/sources")
async def sources(request: Request):
    """Per-source qualified Ingested Counts + Source Health Status.

    Computed from DB source configs + COUNT-by-source aggregates + latest run.
    """
    stores = request.app.state.stores
    db_sources = await stores.sources.get_sources()
    items_by_source = await stores.items.count_by_source()
    raw_by_source = await stores.ingestion_queue.count_by_source()
    result = []
    for s in db_sources:
        latest = await stores.ingestion_runs.latest_for_source(s.id)
        if not s.enabled:
            health = "disabled"
        elif latest is None:
            health = "never_run"
        elif latest.status == "error":
            health = "erroring"
        else:
            health = "healthy"
        result.append({
            "id": s.id,
            "adapter_type": s.adapter_type,
            "enabled": s.enabled,
            "schedule": s.schedule,
            "last_run": latest.finished_at.isoformat() if latest and latest.finished_at else None,
            "items_stored": items_by_source.get(s.adapter_type, 0),
            "raw_enqueued": raw_by_source.get(s.adapter_type, 0),
            "in_flight": raw_by_source.get(s.adapter_type, 0),
            "health_status": health,
        })
    return result


@router.get("/ingestion-timeseries")
async def ingestion_timeseries(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    bucket: str = Query("day"),
):
    stores = request.app.state.stores
    series = await stores.ingestion_runs.timeseries(days=days, bucket=bucket)
    return [{"bucket_ts": ts.isoformat(), "raw_enqueued": n} for ts, n in series]
```

```python
# src/workbench/api/activity.py
from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/activity")
async def activity(request: Request, limit: int = Query(50, ge=1, le=200)):
    """Recent activity rows, promoted out of /api/debug/pipeline."""
    stores = request.app.state.stores
    try:
        rows = await stores.items.pool.fetch(
            "SELECT id, status, source_type, summary, created_at "
            "FROM items ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return [
            {
                "id": r["id"],
                "status": r["status"],
                "source_type": r["source_type"],
                "summary": r["summary"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    except Exception:
        return []
```

Replace `src/workbench/api/jobs.py` entirely:

```python
# src/workbench/api/jobs.py
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
):
    stores = request.app.state.stores
    jobs = await stores.jobs.list_jobs(limit=limit, offset=offset, status=status)
    total = await stores.jobs.count(status=status)
    return {"jobs": jobs, "total": total}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    stores = request.app.state.stores
    job = await stores.jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
```

In `src/workbench/main.py`, register the new routers. Change the `from workbench.api import (...)` block and the include loop:

```python
    from workbench.api import (
        actions, activity, auth_token,
        config as config_api, connections, debug, filter_rules, health, identity,
        items, jobs, memory, messenger, process, queue, sources, stats, triage,
    )
    for r in [
        health.router, items.router, triage.router, process.router,
        filter_rules.router, sources.router, config_api.router,
        memory.router, identity.router, jobs.router, queue.router,
        actions.router, auth_token.router, debug.router,
        stats.router, activity.router, messenger.router, connections.router,
    ]:
        app.include_router(r)
```

> NOTE: `messenger` and `connections` modules are created in later tasks (C1, B4). Until then, add only `stats.router, activity.router` to keep the import valid; append `messenger.router, connections.router` and their imports when those tasks land. For this task, import only `activity, stats` additions and include only `stats.router, activity.router`.

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_stats_api.py -v`
Expected: PASS

> The `/api/stats/sources` and `/ingestion-timeseries` handlers reference `stores.ingestion_runs`, added in Task A5. Those two routes are not exercised by this task's tests. If running the whole suite before A5, `stores.ingestion_runs` will be absent — A5 wires it. Run only `tests/test_stats_api.py` for this task.

- [ ] Step 5: Commit
`git commit -am "feat(api): /api/stats/{overview,queue,sources,ingestion-timeseries}, /api/activity, /api/jobs list"`

---

### Task A5: `ingestion_runs` table + IngestionRunStore + retention
**Files:**
- Modify `src/workbench/models.py` (add `IngestionRun`)
- Create `src/workbench/storage/ingestion_runs.py`
- Modify `src/workbench/storage/base.py` (add to `Stores`)
- Modify `src/workbench/storage/postgres/stores.py` (wire it)
- Create `src/workbench/migrations/versions/005_ingestion_runs.py`
- Modify `src/workbench/config.py` (`RetentionConfig.ingestion_runs_days`)
- Modify `src/workbench/pipeline/scheduler.py` (`run_retention_cleanup`)
- Modify `tests/conftest.py` (add `ingestion_runs` to TABLES)
- Test `tests/test_ingestion_runs.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_ingestion_runs.py
import pytest
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_start_finish_run(stores):
    run_id = await stores.ingestion_runs.start_run("src-1")
    assert run_id
    latest = await stores.ingestion_runs.latest_for_source("src-1")
    assert latest.status == "running"
    assert latest.raw_enqueued == 0

    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=7)
    latest = await stores.ingestion_runs.latest_for_source("src-1")
    assert latest.status == "success"
    assert latest.raw_enqueued == 7
    assert latest.finished_at is not None


@pytest.mark.asyncio
async def test_error_run(stores):
    run_id = await stores.ingestion_runs.start_run("src-2")
    await stores.ingestion_runs.error_run(run_id, "boom")
    latest = await stores.ingestion_runs.latest_for_source("src-2")
    assert latest.status == "error"
    assert latest.error == "boom"


@pytest.mark.asyncio
async def test_latest_for_source_none(stores):
    assert await stores.ingestion_runs.latest_for_source("nope") is None


@pytest.mark.asyncio
async def test_timeseries_buckets_by_day(stores):
    run_id = await stores.ingestion_runs.start_run("src-3")
    await stores.ingestion_runs.finish_run(run_id, raw_enqueued=5)
    run_id2 = await stores.ingestion_runs.start_run("src-3")
    await stores.ingestion_runs.finish_run(run_id2, raw_enqueued=3)
    series = await stores.ingestion_runs.timeseries(days=14, bucket="day")
    total = sum(n for _, n in series)
    assert total == 8


@pytest.mark.asyncio
async def test_delete_older_than(stores, pg_pool):
    run_id = await stores.ingestion_runs.start_run("src-old")
    await pg_pool.execute(
        "UPDATE ingestion_runs SET started_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=100), run_id,
    )
    deleted = await stores.ingestion_runs.delete_older_than(30)
    assert deleted == 1
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_ingestion_runs.py -v`
Expected: `AttributeError: 'Stores' object has no attribute 'ingestion_runs'`

- [ ] Step 3: Write minimal implementation

In `src/workbench/models.py`, add after the `Fact`/`EntityKnowledge` block (anywhere top-level):

```python
class IngestionRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "running"  # running | success | error
    raw_enqueued: int = 0
    error: str | None = None
```

(Ensure `from datetime import datetime, timezone` and `import uuid` are present at the top of `models.py`; `datetime` and `uuid` already are — add `timezone` to the datetime import if missing.)

```python
# src/workbench/storage/ingestion_runs.py
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import asyncpg

from workbench.models import IngestionRun


class IngestionRunStore(ABC):
    @abstractmethod
    async def start_run(self, source_id: str) -> str: ...
    @abstractmethod
    async def finish_run(self, run_id: str, raw_enqueued: int) -> None: ...
    @abstractmethod
    async def error_run(self, run_id: str, error: str) -> None: ...
    @abstractmethod
    async def latest_for_source(self, source_id: str) -> IngestionRun | None: ...
    @abstractmethod
    async def timeseries(self, days: int, bucket: str) -> list[tuple[datetime, int]]: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int: ...


class PgIngestionRunStore(IngestionRunStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def start_run(self, source_id: str) -> str:
        run_id = str(uuid.uuid4())
        await self.pool.execute(
            "INSERT INTO ingestion_runs (id, source_id, started_at, status, raw_enqueued) "
            "VALUES ($1, $2, $3, 'running', 0)",
            run_id, source_id, datetime.now(timezone.utc),
        )
        return run_id

    async def finish_run(self, run_id: str, raw_enqueued: int) -> None:
        await self.pool.execute(
            "UPDATE ingestion_runs SET status = 'success', finished_at = $1, "
            "raw_enqueued = $2 WHERE id = $3",
            datetime.now(timezone.utc), raw_enqueued, run_id,
        )

    async def error_run(self, run_id: str, error: str) -> None:
        await self.pool.execute(
            "UPDATE ingestion_runs SET status = 'error', finished_at = $1, error = $2 "
            "WHERE id = $3",
            datetime.now(timezone.utc), error, run_id,
        )

    async def latest_for_source(self, source_id: str) -> IngestionRun | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM ingestion_runs WHERE source_id = $1 "
            "ORDER BY started_at DESC LIMIT 1",
            source_id,
        )
        return self._row(row) if row else None

    async def timeseries(self, days: int, bucket: str) -> list[tuple[datetime, int]]:
        if bucket not in ("day", "hour", "week"):
            bucket = "day"
        rows = await self.pool.fetch(
            f"SELECT date_trunc('{bucket}', started_at) AS ts, "
            "COALESCE(SUM(raw_enqueued), 0) AS total FROM ingestion_runs "
            "WHERE started_at >= NOW() - INTERVAL '1 day' * $1 "
            "GROUP BY ts ORDER BY ts",
            days,
        )
        return [(r["ts"], int(r["total"])) for r in rows]

    async def delete_older_than(self, days: int) -> int:
        result = await self.pool.execute(
            "DELETE FROM ingestion_runs WHERE started_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(result.split()[-1])

    @staticmethod
    def _row(row: asyncpg.Record) -> IngestionRun:
        return IngestionRun(
            id=row["id"],
            source_id=row["source_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            raw_enqueued=row["raw_enqueued"],
            error=row["error"],
        )
```

In `src/workbench/storage/base.py`, import and add to `Stores`. At the top:

```python
from workbench.storage.ingestion_runs import IngestionRunStore
```

Add the constructor param + attribute (insert `ingestion_runs` after `ingestion_queue` in both the signature and body):

```python
        ingestion_queue: IngestionQueueStore,
        ingestion_runs: IngestionRunStore,
        close_fn=None,
    ):
        ...
        self.ingestion_queue = ingestion_queue
        self.ingestion_runs = ingestion_runs
        self._close_fn = close_fn
```

In `src/workbench/storage/postgres/stores.py`:

```python
from workbench.storage.ingestion_runs import PgIngestionRunStore
```

and in the `Stores(...)` call add:

```python
        ingestion_queue=PgIngestionQueueStore(pool),
        ingestion_runs=PgIngestionRunStore(pool),
        close_fn=close,
```

Create the migration:

```python
# src/workbench/migrations/versions/005_ingestion_runs.py
"""ingestion_runs table.

Revision ID: 005
Revises: 004
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("raw_enqueued", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_ingestion_runs_source_started",
        "ingestion_runs", ["source_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_source_started", "ingestion_runs")
    op.drop_table("ingestion_runs")
```

In `src/workbench/config.py`, add to `RetentionConfig`:

```python
    ingestion_runs_days: int = 30
```

In `src/workbench/pipeline/scheduler.py`, add to `run_retention_cleanup` (before `total = sum(...)`):

```python
    results["ingestion_runs"] = await stores.ingestion_runs.delete_older_than(config.ingestion_runs_days)
```

In `tests/conftest.py`, add `"ingestion_runs"` to the `TABLES` list (so truncation covers it):

```python
TABLES = [
    "ingestion_runs",
    "ingestion_queue",
    "config",
    "jobs",
    "source_configs",
    "processed",
    "enrichment_trace",
    "filter_rules",
    "interaction_log",
    "triage_cards",
    "plans",
    "items",
]
```

- [ ] Step 4: Run test to verify it passes
Run: `alembic upgrade head && python -m pytest tests/test_ingestion_runs.py tests/test_stats_api.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(storage): ingestion_runs table + IngestionRunStore + retention cleanup"`

---

## PHASE B — Scheduler & sources backend

### Task B1: Refactor scheduler to `_poll_one_source` with run hooks + source_id watermark
**Files:**
- Modify `src/workbench/pipeline/scheduler.py`
- Test `tests/test_poll_one_source.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_poll_one_source.py
import pytest
from unittest.mock import AsyncMock
from workbench.config import AppConfig, StorageConfig
from workbench.memory.noop import NoopMemoryLayer
from workbench.models import JobTrigger, RawItem, SourceConfig
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.scheduler import WorkbenchScheduler


def _config():
    return AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "t"},
    )


class _FakeSource:
    def __init__(self, items):
        self._items = items
        self.since_seen = "unset"

    def adapter_type(self):
        return "github"

    async def poll(self, since=None):
        self.since_seen = since
        return self._items


@pytest.mark.asyncio
async def test_poll_one_source_records_run_and_watermark(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    pipeline.enqueue = AsyncMock()
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    adapter = _FakeSource([
        RawItem(id="r1", source_type="github", source_label="x", raw_text="t"),
        RawItem(id="r2", source_type="github", source_label="y", raw_text="t2"),
    ])
    sched = WorkbenchScheduler(stores, NoopMemoryLayer(), pipeline, None, _config(),
                               sources=[adapter], llm=mock_llm)
    sched._source_by_id = {src.id: adapter}

    await sched._poll_one_source(src.id, JobTrigger.POLL)

    latest = await stores.ingestion_runs.latest_for_source(src.id)
    assert latest.status == "success"
    assert latest.raw_enqueued == 2
    assert pipeline.enqueue.await_count == 2
    wm = await stores.config.get(f"source_last_polled:{src.id}")
    assert wm is not None


@pytest.mark.asyncio
async def test_poll_one_source_error_marks_run(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)

    class _Boom:
        def adapter_type(self): return "github"
        async def poll(self, since=None): raise RuntimeError("kaboom")

    sched = WorkbenchScheduler(stores, NoopMemoryLayer(), pipeline, None, _config(),
                               sources=[], llm=mock_llm)
    sched._source_by_id = {src.id: _Boom()}

    await sched._poll_one_source(src.id, JobTrigger.POLL)
    latest = await stores.ingestion_runs.latest_for_source(src.id)
    assert latest.status == "error"
    assert "kaboom" in latest.error


@pytest.mark.asyncio
async def test_poll_one_source_migrates_legacy_watermark(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    pipeline.enqueue = AsyncMock()
    src = SourceConfig(adapter_type="github", config={}, enabled=True)
    await stores.sources.upsert_source(src)
    await stores.config.set("source_last_polled:github", "2026-06-01T00:00:00+00:00")
    adapter = _FakeSource([])
    sched = WorkbenchScheduler(stores, NoopMemoryLayer(), pipeline, None, _config(),
                               sources=[adapter], llm=mock_llm)
    sched._source_by_id = {src.id: adapter}

    await sched._poll_one_source(src.id, JobTrigger.POLL)
    # legacy value copied to source_id key and used as since=
    assert adapter.since_seen is not None
    assert adapter.since_seen.year == 2026 and adapter.since_seen.month == 6
    # legacy key left in place (non-destructive)
    assert await stores.config.get("source_last_polled:github") is not None
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_poll_one_source.py -v`
Expected: `AttributeError: 'WorkbenchScheduler' object has no attribute '_poll_one_source'`

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py`, add `asyncio` import at top and a per-source lock map in `__init__`:

```python
import asyncio
```

In `__init__`, after `self.scheduler = AsyncIOScheduler(...)`:

```python
        self._source_locks: dict[str, asyncio.Lock] = {}
        # Maps source_id -> live adapter instance (kept in sync by hot-reload).
        self._source_by_id: dict[str, object] = {}
```

Add the new method (place it just above `_poll_sources`):

```python
    def _lock_for(self, source_id: str) -> asyncio.Lock:
        lock = self._source_locks.get(source_id)
        if lock is None:
            lock = asyncio.Lock()
            self._source_locks[source_id] = lock
        return lock

    async def _read_watermark(self, source_id: str, adapter_type: str) -> datetime | None:
        stored = await self.stores.config.get(f"source_last_polled:{source_id}")
        if stored is None:
            # One-time non-destructive migration from the legacy adapter_type key.
            legacy = await self.stores.config.get(f"source_last_polled:{adapter_type}")
            if legacy is not None:
                await self.stores.config.set(f"source_last_polled:{source_id}", legacy)
                stored = legacy
        return datetime.fromisoformat(stored) if stored else None

    async def _poll_one_source(self, source_id: str, trigger: JobTrigger) -> None:
        """Shared by Source Jobs (POLL) and manual poll (MANUAL).

        Guarded by a per-source asyncio.Lock; owns Ingestion Run start/finish/error.
        """
        adapter = self._source_by_id.get(source_id)
        if adapter is None:
            logger.warning("No live adapter for source_id=%s", source_id)
            return
        adapter_type = adapter.adapter_type()

        async with self._lock_for(source_id):
            connection = getattr(adapter, "_connection", None)
            if connection is not None and hasattr(connection, "is_healthy"):
                if not connection.is_healthy():
                    logger.warning("Skipping %s: connection unhealthy", source_id)
                    return

            run_id = await self.stores.ingestion_runs.start_run(source_id)
            try:
                since = await self._read_watermark(source_id, adapter_type)
                raw_items = await adapter.poll(since=since)
                enqueued = 0
                for raw_item in raw_items:
                    try:
                        await self.pipeline.enqueue(
                            raw_item.raw_text,
                            raw_item.source_type,
                            source_id=raw_item.id,
                            urgency_signals=raw_item.urgency_signals,
                            trigger=trigger,
                        )
                        enqueued += 1
                    except Exception as e:
                        logger.error("Failed to enqueue item %s from %s: %s",
                                     raw_item.id, source_id, e)
                await self.stores.config.set(
                    f"source_last_polled:{source_id}",
                    datetime.now(timezone.utc).isoformat(),
                )
                await self.stores.ingestion_runs.finish_run(run_id, enqueued)
                logger.info("Polled source %s (%s): %d items (since=%s)",
                            source_id, adapter_type, enqueued, since)
            except Exception as e:
                await self.stores.ingestion_runs.error_run(run_id, str(e))
                logger.error("Source %s poll failed: %s", source_id, e)
```

Leave the old `_poll_sources` in place for now (B2 removes its scheduling); it is unused once B2 registers per-source jobs.

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_poll_one_source.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(scheduler): _poll_one_source with run hooks, per-source lock, source_id watermark + legacy migration"`

---

### Task B2: Per-source Source Jobs + runtime job management + startup wiring
**Files:**
- Modify `src/workbench/pipeline/scheduler.py`
- Modify `src/workbench/main.py` (build `_source_by_id` at startup; assign stable ids)
- Test `tests/test_source_jobs.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_source_jobs.py
import pytest
from unittest.mock import AsyncMock
from workbench.config import AppConfig, StorageConfig
from workbench.memory.noop import NoopMemoryLayer
from workbench.models import SourceConfig
from workbench.pipeline.engine import PipelineEngine
from workbench.pipeline.scheduler import WorkbenchScheduler


def _config():
    return AppConfig(
        storage=StorageConfig(postgres_dsn="postgres://x"),
        llm={"class": "workbench.providers.llm.anthropic.AnthropicLLM", "api_key": "t"},
    )


class _FakeSource:
    def adapter_type(self): return "github"
    async def poll(self, since=None): return []


def _sched(stores):
    mock_llm = AsyncMock()
    pipeline = PipelineEngine(stores, NoopMemoryLayer(), mock_llm, None)
    return WorkbenchScheduler(stores, NoopMemoryLayer(), pipeline, None, _config(),
                              sources=[], llm=mock_llm)


@pytest.mark.asyncio
async def test_add_source_job_creates_cron_job(stores):
    sched = _sched(stores)
    src = SourceConfig(adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True)
    sched.add_source_job(src, _FakeSource())
    job = sched.scheduler.get_job(f"poll_source:{src.id}")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    assert f"poll_source:{src.id}" in sched._source_by_id is False  # mapping keyed by id
    assert src.id in sched._source_by_id


@pytest.mark.asyncio
async def test_disabled_source_has_no_job(stores):
    sched = _sched(stores)
    src = SourceConfig(adapter_type="github", config={}, schedule="*/15 * * * *", enabled=False)
    sched.add_source_job(src, _FakeSource())
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is None


@pytest.mark.asyncio
async def test_reschedule_and_remove_source_job(stores):
    sched = _sched(stores)
    src = SourceConfig(adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True)
    sched.add_source_job(src, _FakeSource())
    src2 = src.model_copy(update={"schedule": "0 * * * *"})
    sched.reschedule_source_job(src2, _FakeSource())
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is not None
    sched.remove_source_job(src.id)
    assert sched.scheduler.get_job(f"poll_source:{src.id}") is None
    assert src.id not in sched._source_by_id


@pytest.mark.asyncio
async def test_no_global_poll_sources_job(stores):
    sched = _sched(stores)
    src = SourceConfig(adapter_type="github", config={}, schedule="*/15 * * * *", enabled=True)
    sched._source_by_id = {src.id: _FakeSource()}
    sched._db_sources = [src]
    sched.scheduler.start()
    try:
        assert sched.scheduler.get_job("poll_sources") is None
    finally:
        sched.scheduler.shutdown(wait=False)
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_source_jobs.py -v`
Expected: `AttributeError: 'WorkbenchScheduler' object has no attribute 'add_source_job'`

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py`, add the import:

```python
from apscheduler.triggers.cron import CronTrigger
```

Add to `__init__` (after `self._source_by_id = {}`):

```python
        # Stable DB source configs the scheduler manages (set at startup).
        self._db_sources: list = []
```

Add the runtime job-management helpers (place above `_poll_one_source`):

```python
    def _cron_trigger(self, schedule: str) -> CronTrigger:
        return CronTrigger.from_crontab(schedule, timezone=ZoneInfo(self.config.logging.timezone))

    def add_source_job(self, source, adapter) -> None:
        """Register one Source Job (CronTrigger) for an enabled source."""
        self._source_by_id[source.id] = adapter
        if not source.enabled:
            return
        self.scheduler.add_job(
            self._poll_one_source,
            self._cron_trigger(source.schedule),
            id=f"poll_source:{source.id}",
            args=[source.id, JobTrigger.POLL],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    def reschedule_source_job(self, source, adapter) -> None:
        self.remove_source_job(source.id)
        self.add_source_job(source, adapter)

    def remove_source_job(self, source_id: str) -> None:
        job = self.scheduler.get_job(f"poll_source:{source_id}")
        if job is not None:
            self.scheduler.remove_job(f"poll_source:{source_id}")
        self._source_by_id.pop(source_id, None)
        self._source_locks.pop(source_id, None)
```

Modify `start()` to register one Source Job per enabled DB source (with stagger) instead of the global `poll_sources` job, and to demote `poll_interval_minutes` to `alert_check` only. Replace the `jobs` list construction and the `if self.sources:` block:

```python
    def start(self):
        jobs = [
            ("triage_queue", "interval",
             {"seconds": self.config.triage.triage_poll_interval_seconds},
             self._manage_triage_queue),
            ("briefing", "cron",
             {"hour": self.config.scheduler.morning_briefing_hour},
             self._morning_briefing),
            ("expire_cards", "cron", {"hour": 3}, self._expire_cards),
        ]
        if self.config.alerting.enabled:
            jobs.append((
                "alert_check", "interval",
                {"minutes": self.config.scheduler.poll_interval_minutes},
                self._alert_check,
            ))
        for job_id, trigger, kwargs, func in jobs:
            logger.info("Scheduling job '%s' (%s)", job_id, trigger)
            self.scheduler.add_job(func, trigger, id=job_id, **kwargs)

        # Per-source Source Jobs (replaces the global poll_sources interval job).
        stagger = 0
        for source in self._db_sources:
            adapter = self._source_by_id.get(source.id)
            if adapter is None or not source.enabled:
                continue
            self.scheduler.add_job(
                self._poll_one_source,
                self._cron_trigger(source.schedule),
                id=f"poll_source:{source.id}",
                args=[source.id, JobTrigger.POLL],
                max_instances=1, coalesce=True, replace_existing=True,
                next_run_time=datetime.now(ZoneInfo(self.config.logging.timezone))
                + timedelta(seconds=stagger),
            )
            stagger += 7
            logger.info("Scheduled Source Job 'poll_source:%s' (%s)", source.id, source.schedule)

        self.scheduler.start()
```

Delete the now-unused `_poll_sources` method.

In `src/workbench/main.py` lifespan, after `app.state.sources = create_providers_from_list(...)`, build the DB-source view and the id->adapter map. Insert before constructing the scheduler:

```python
    # Build DB source configs (config.yml is source of truth) + id->adapter map.
    db_sources = await app.state.stores.sources.get_sources()
    source_by_id: dict[str, object] = {}
    # Pair each live adapter with its DB SourceConfig by adapter_type order.
    by_type: dict[str, list] = {}
    for adapter in app.state.sources:
        inner = getattr(adapter, "_inner", adapter)
        by_type.setdefault(inner.adapter_type(), []).append(adapter)
    for s in db_sources:
        bucket = by_type.get(s.adapter_type, [])
        if bucket:
            source_by_id[s.id] = bucket.pop(0)
```

Then pass them onto the scheduler after construction:

```python
    app.state.scheduler = WorkbenchScheduler(
        app.state.stores, app.state.memory, app.state.pipeline,
        app.state.messenger, config, sources=app.state.sources,
        llm=app.state.llm,
    )
    app.state.scheduler._db_sources = db_sources
    app.state.scheduler._source_by_id = source_by_id
    app.state.scheduler.start()
```

> NOTE: stable `source.id` is written to YAML by Task B3/B4 Config Write-Back. The first-run pairing above relies on DB source configs existing; for the YAML-driven sources, B4's startup sync upserts each YAML `sources:` entry (with its stable id) into `source_configs` so `get_sources()` returns them. Until B4, `db_sources` may be empty and no Source Jobs are scheduled — that is acceptable for this task (tests drive the scheduler directly).

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_source_jobs.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(scheduler): per-source CronTrigger Source Jobs + runtime add/reschedule/remove + startup stagger"`

---

### Task B3: Config Write-Back module (ruamel round-trip)
**Files:**
- Create `src/workbench/config_writer.py`
- Add `ruamel.yaml` to project deps (`pyproject.toml` dependencies)
- Test `tests/test_config_writer.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_config_writer.py
import pytest
from workbench.config_writer import write_source, delete_source, write_messenger


SAMPLE = """\
version: 0.4.0
# top comment
server:
  api_token: ${oc.env:WORKBENCH_TOKEN}
sources:
  - id: src-existing
    adapter_type: github
    # repo list below
    config:
      repos:
        - meta/workbench
    schedule: "*/15 * * * *"
    enabled: true
messenger:
  class: workbench.providers.messenger.gchat.GChatMessenger
  space_id: spaces/AAA
  service_account_key_path: ${oc.env:SA_PATH}
"""


def _write(tmp_path, text):
    p = tmp_path / "config.yml"
    p.write_text(text)
    return str(p)


def test_add_source_preserves_interpolations_and_comments(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_source(path, {
        "id": "src-new", "adapter_type": "github",
        "config": {"repos": ["meta/other"]},
        "schedule": "0 * * * *", "enabled": True,
    })
    out = (tmp_path / "config.yml").read_text()
    assert "${oc.env:WORKBENCH_TOKEN}" in out      # interpolation preserved
    assert "${oc.env:SA_PATH}" in out              # messenger secret untouched
    assert "# top comment" in out                  # comment preserved
    assert "# repo list below" in out              # nested comment preserved
    assert "src-new" in out and "src-existing" in out


def test_edit_existing_source_updates_in_place(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_source(path, {
        "id": "src-existing", "adapter_type": "github",
        "config": {"repos": ["meta/workbench", "meta/added"]},
        "schedule": "*/30 * * * *", "enabled": False,
    })
    out = (tmp_path / "config.yml").read_text()
    assert "meta/added" in out
    assert "*/30 * * * *" in out
    assert "enabled: false" in out
    # only one src-existing entry remains (edited, not duplicated)
    assert out.count("id: src-existing") == 1


def test_delete_source_removes_node(tmp_path):
    path = _write(tmp_path, SAMPLE)
    delete_source(path, "src-existing")
    out = (tmp_path / "config.yml").read_text()
    assert "src-existing" not in out
    assert "${oc.env:WORKBENCH_TOKEN}" in out


def test_write_messenger_preserves_secret_interpolation(tmp_path):
    path = _write(tmp_path, SAMPLE)
    write_messenger(path, {
        "class": "workbench.providers.messenger.gchat.GChatMessenger",
        "space_id": "spaces/BBB",
        "timeout_seconds": 10,
    })
    out = (tmp_path / "config.yml").read_text()
    assert "spaces/BBB" in out
    # secret interpolation node preserved (not overwritten with a resolved value)
    assert "${oc.env:SA_PATH}" in out


def test_no_resolved_secret_ever_written(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_TOKEN", "RESOLVED-SECRET")
    monkeypatch.setenv("SA_PATH", "/secret/sa.json")
    path = _write(tmp_path, SAMPLE)
    write_source(path, {
        "id": "src-new", "adapter_type": "github",
        "config": {"repos": ["x/y"]}, "schedule": "0 * * * *", "enabled": True,
    })
    out = (tmp_path / "config.yml").read_text()
    assert "RESOLVED-SECRET" not in out
    assert "/secret/sa.json" not in out
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_config_writer.py -v`
Expected: `ModuleNotFoundError: No module named 'workbench.config_writer'`

- [ ] Step 3: Write minimal implementation

Add `ruamel.yaml` to `pyproject.toml` `[project] dependencies`.

```python
# src/workbench/config_writer.py
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def _load(path: str):
    with open(path, "r") as f:
        return _yaml.load(f)


def _atomic_dump(path: str, data) -> None:
    """Write atomically: temp file in the same dir + os.replace."""
    target = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            _yaml.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_source(path: str, source: dict) -> None:
    """Insert or update a single sources: node, keyed by id. Round-trip preserving."""
    data = _load(path)
    sources = data.get("sources")
    if sources is None:
        sources = []
        data["sources"] = sources
    for i, existing in enumerate(sources):
        if existing.get("id") == source["id"]:
            sources[i] = source
            break
    else:
        sources.append(source)
    _atomic_dump(path, data)


def delete_source(path: str, source_id: str) -> None:
    data = _load(path)
    sources = data.get("sources") or []
    data["sources"] = [s for s in sources if s.get("id") != source_id]
    _atomic_dump(path, data)


def write_messenger(path: str, messenger: dict) -> None:
    """Replace the messenger: node's safe fields, preserving secret interpolations.

    Only the provided keys are written; pre-existing keys that carry
    ${oc.env:...} interpolations (e.g. service_account_key_path) are retained.
    """
    data = _load(path)
    existing = data.get("messenger")
    if existing is None:
        data["messenger"] = messenger
    else:
        for k, v in messenger.items():
            existing[k] = v
    _atomic_dump(path, data)
```

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_config_writer.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(config): ruamel Config Write-Back module (atomic, interpolation/comment preserving)"`

---

### Task B4: Source management API (allowlist + write-back + Targeted Hot-Reload)
**Files:**
- Modify `src/workbench/api/sources.py`
- Create `src/workbench/api/connections.py`
- Modify `src/workbench/main.py` (register `connections.router`; `app.state.reload_lock`; YAML->DB source sync at startup)
- Test `tests/test_sources_api.py`

> CHANGE OF EXISTING CONTRACT: the old `tests/test_api.py::test_sources_crud` posts `{"adapter_type": "diff", "config": {...}}`. The allowlist no longer includes `diff`, and `adapter_type` is now restricted to `{github, email, calendar, chat}`. Update that test to use `adapter_type: "github"` with `config: {"repos": ["x/y"]}` and to expect the new create/patch/delete behavior (Step 3 below shows the new test). Replace `test_sources_crud` accordingly.

- [ ] Step 1: Write the failing test

```python
# tests/test_sources_api.py
import os
import pytest
from httpx import AsyncClient, ASGITransport


SAMPLE_CONFIG = """\
version: 0.4.0
server:
  api_token: dev-token-change-me
storage:
  postgres_dsn: ${oc.env:WB_TEST_DSN}
llm:
  class: workbench.providers.llm.anthropic.AnthropicLLM
  api_key: test
sources: []
"""


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_TEST_DSN", "postgres://workbench:workbench@localhost:5432/workbench")
    p = tmp_path / "config.yml"
    p.write_text(SAMPLE_CONFIG)
    monkeypatch.setenv("WORKBENCH_CONFIG", str(p))
    return str(p)


@pytest.mark.asyncio
async def test_adapter_types_lists_allowlist(client):
    r = await client.get("/api/sources/adapter-types")
    assert r.status_code == 200
    types = {t["adapter_type"] for t in r.json()}
    assert types == {"github", "email", "calendar", "chat"}
    gh = next(t for t in r.json() if t["adapter_type"] == "github")
    assert gh["requires_connection"] is False
    assert "properties" in gh["model_json_schema"]
    email = next(t for t in r.json() if t["adapter_type"] == "email")
    assert email["requires_connection"] is True


@pytest.mark.asyncio
async def test_create_source_writes_yaml_and_db(client, app_with_state, config_path):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "github",
        "config": {"repos": ["meta/workbench"]},
        "schedule": "*/15 * * * *",
        "enabled": True,
    })
    assert r.status_code == 200
    source_id = r.json()["id"]
    out = open(config_path).read()
    assert source_id in out
    assert "meta/workbench" in out
    db = await app_with_state.state.stores.sources.get_source(source_id)
    assert db is not None and db.adapter_type == "github"


@pytest.mark.asyncio
async def test_create_rejects_unknown_adapter_type(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "diff", "config": {}, "schedule": "*/15 * * * *", "enabled": True,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_bad_cron(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "github", "config": {"repos": []},
        "schedule": "not a cron", "enabled": True,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_invalid_config_field(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "github", "config": {"repos": "should-be-a-list"},
        "schedule": "*/15 * * * *", "enabled": True,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_rejects_adapter_type_change(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "github", "config": {"repos": []},
        "schedule": "*/15 * * * *", "enabled": True,
    })
    source_id = r.json()["id"]
    r = await client.patch(f"/api/sources/{source_id}", json={"adapter_type": "email"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_removes_yaml_and_db(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    r = await client.post("/api/sources", json={
        "adapter_type": "github", "config": {"repos": []},
        "schedule": "*/15 * * * *", "enabled": True,
    })
    source_id = r.json()["id"]
    r = await client.delete(f"/api/sources/{source_id}")
    assert r.status_code == 200
    out = open(config_path).read()
    assert source_id not in out
    assert await app_with_state.state.stores.sources.get_source(source_id) is None


@pytest.mark.asyncio
async def test_create_email_source_without_connection_rejected(client, config_path, app_with_state):
    app_with_state.state.config_path = config_path
    app_with_state.state.connections = {}
    r = await client.post("/api/sources", json={
        "adapter_type": "email", "config": {}, "connection": "google",
        "schedule": "*/15 * * * *", "enabled": True,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_connections_endpoint_no_secrets(client, app_with_state):
    class _Conn:
        def is_healthy(self): return True
    app_with_state.state.connections = {"google": _Conn()}
    r = await client.get("/api/connections")
    assert r.status_code == 200
    data = r.json()
    assert data == [{"name": "google", "healthy": True}]


@pytest.mark.asyncio
async def test_sources_require_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/sources", json={})
        assert r.status_code == 401
```

Add `app.state.reload_lock` and `app.state.config_path` to the test fixture so hot-reload runs. In `tests/test_api.py`'s `app_with_state` fixture, add after `test_app.state.sources = []`:

```python
    import asyncio as _asyncio
    test_app.state.reload_lock = _asyncio.Lock()
    test_app.state.connections = {}
    test_app.state.config_path = None
    test_app.state.scheduler = None
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_sources_api.py -v`
Expected: 404 on `/api/sources/adapter-types` (route not defined)

- [ ] Step 3: Write minimal implementation

Replace `src/workbench/api/sources.py` entirely:

```python
# src/workbench/api/sources.py
from __future__ import annotations

import importlib
import os

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from workbench.config_writer import delete_source as yaml_delete_source
from workbench.config_writer import write_source as yaml_write_source
from workbench.models import JobTrigger, SourceConfig, SourceConfigUpdate

router = APIRouter(prefix="/api", tags=["sources"])

# Import-gadget guard: short name -> dotted class path. No client class path accepted.
ADAPTER_ALLOWLIST = {
    "github": "workbench.providers.source.github.GitHubSourceAdapter",
    "email": "workbench.providers.source.gmail.GmailAdapter",
    "calendar": "workbench.providers.source.gcalendar.GCalendarAdapter",
    "chat": "workbench.providers.source.gchat.GChatAdapter",
}


def _load_adapter_cls(adapter_type: str):
    class_path = ADAPTER_ALLOWLIST[adapter_type]
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _requires_connection(cls) -> bool:
    import inspect
    return "connection" in inspect.signature(cls.__init__).parameters


class CreateSourceBody(BaseModel):
    adapter_type: str
    config: dict = {}
    schedule: str = "*/15 * * * *"
    enabled: bool = True
    connection: str | None = None


def _validate_cron(schedule: str, tz: str) -> None:
    try:
        from zoneinfo import ZoneInfo
        CronTrigger.from_crontab(schedule, timezone=ZoneInfo(tz))
    except Exception as e:
        raise HTTPException(422, f"Invalid cron schedule: {e}")


def _validate_config(cls, config: dict) -> None:
    if hasattr(cls, "ProviderConfig"):
        try:
            cls.ProviderConfig(**config)
        except ValidationError as e:
            raise HTTPException(422, {"config_errors": e.errors()})


@router.get("/sources/adapter-types")
async def adapter_types(request: Request):
    result = []
    for name, class_path in ADAPTER_ALLOWLIST.items():
        cls = _load_adapter_cls(name)
        schema = cls.ProviderConfig.model_json_schema() if hasattr(cls, "ProviderConfig") else {}
        result.append({
            "adapter_type": name,
            "model_json_schema": schema,
            "requires_connection": _requires_connection(cls),
        })
    return result


@router.get("/sources")
async def list_sources(request: Request):
    stores = request.app.state.stores
    return await stores.sources.get_sources()


def _config_path(request: Request) -> str:
    path = getattr(request.app.state, "config_path", None)
    return path or os.environ.get("WORKBENCH_CONFIG", "config.yml")


async def _instantiate(request: Request, adapter_type: str, config: dict, connection_name: str | None):
    cls = _load_adapter_cls(adapter_type)
    connections = getattr(request.app.state, "connections", {})
    kwargs = {}
    if _requires_connection(cls):
        if not connection_name or connection_name not in connections:
            raise HTTPException(
                422,
                f"adapter_type '{adapter_type}' requires a defined connection; "
                f"'{connection_name}' is not configured (connections are YAML-only + restart).",
            )
        kwargs["connection"] = connections[connection_name]
    typed = cls.ProviderConfig(**config) if hasattr(cls, "ProviderConfig") else None
    return cls(typed, **kwargs) if typed is not None else cls(**kwargs)


@router.post("/sources")
async def create_source(body: CreateSourceBody, request: Request):
    if body.adapter_type not in ADAPTER_ALLOWLIST:
        raise HTTPException(422, f"Unknown adapter_type '{body.adapter_type}'")
    cls = _load_adapter_cls(body.adapter_type)
    _validate_cron(body.schedule, request.app.state.config.logging.timezone)
    _validate_config(cls, body.config)

    source = SourceConfig(
        adapter_type=body.adapter_type, config=body.config,
        schedule=body.schedule, enabled=body.enabled,
    )

    lock = request.app.state.reload_lock
    async with lock:
        # validate -> instantiate -> write YAML -> swap
        adapter = await _instantiate(request, body.adapter_type, body.config, body.connection)
        node = {
            "id": source.id, "adapter_type": source.adapter_type,
            "config": source.config, "schedule": source.schedule,
            "enabled": source.enabled,
        }
        if body.connection:
            node["connection"] = body.connection
        yaml_write_source(_config_path(request), node)
        await request.app.state.stores.sources.upsert_source(source)
        # copy-on-write swap into app.state + scheduler
        request.app.state.sources = list(request.app.state.sources) + [adapter]
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            scheduler._db_sources = list(scheduler._db_sources) + [source]
            scheduler.add_source_job(source, adapter)

    import structlog
    structlog.get_logger(__name__).info(
        "source_created", source_id=source.id, adapter_type=source.adapter_type,
    )
    return source


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, updates: SourceConfigUpdate, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if getattr(updates, "adapter_type", None) is not None and updates.adapter_type != source.adapter_type:
        raise HTTPException(422, "adapter_type is immutable")

    cls = _load_adapter_cls(source.adapter_type)
    new_config = updates.config if updates.config is not None else source.config
    new_schedule = updates.schedule if updates.schedule is not None else source.schedule
    new_enabled = updates.enabled if updates.enabled is not None else source.enabled
    _validate_cron(new_schedule, request.app.state.config.logging.timezone)
    _validate_config(cls, new_config)

    lock = request.app.state.reload_lock
    async with lock:
        adapter = await _instantiate(request, source.adapter_type, new_config, getattr(updates, "connection", None))
        node = {
            "id": source.id, "adapter_type": source.adapter_type,
            "config": new_config, "schedule": new_schedule, "enabled": new_enabled,
        }
        yaml_write_source(_config_path(request), node)
        updated = await stores.sources.update_source(
            source_id, SourceConfigUpdate(config=new_config, schedule=new_schedule, enabled=new_enabled),
        )
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.reschedule_source_job(updated, adapter)

    import structlog
    structlog.get_logger(__name__).info("source_updated", source_id=source_id)
    return updated


@router.delete("/sources/{source_id}")
async def remove_source(source_id: str, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    lock = request.app.state.reload_lock
    async with lock:
        yaml_delete_source(_config_path(request), source_id)
        await stores.sources.pool.execute("DELETE FROM source_configs WHERE id = $1", source_id)
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.remove_source_job(source_id)
            scheduler._db_sources = [s for s in scheduler._db_sources if s.id != source_id]
    import structlog
    structlog.get_logger(__name__).info("source_deleted", source_id=source_id)
    return {"status": "deleted"}


@router.post("/sources/{source_id}/poll")
async def poll_source_now(source_id: str, request: Request):
    stores = request.app.state.stores
    source = await stores.sources.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(503, "Scheduler not available")
    await scheduler._poll_one_source(source_id, JobTrigger.MANUAL)
    return {"status": "polled"}
```

> The `SourceConfigUpdate` model must accept `adapter_type` and `connection` so the PATCH guard can detect a change. In `src/workbench/models.py`, extend it:

```python
class SourceConfigUpdate(BaseModel):
    config: dict | None = None
    schedule: str | None = None
    enabled: bool | None = None
    adapter_type: str | None = None
    connection: str | None = None
```

> But `PgSourceConfigStore.update_source` only handles `config/schedule/enabled` — leave it; the API constructs a clean `SourceConfigUpdate(config=, schedule=, enabled=)` before calling the store.

Create the connections endpoint:

```python
# src/workbench/api/connections.py
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["connections"])


@router.get("/connections")
async def list_connections(request: Request):
    """Connection names + health only — never service_account_key_path/tokens/DSN."""
    connections = getattr(request.app.state, "connections", {})
    result = []
    for name, conn in connections.items():
        try:
            healthy = bool(conn.is_healthy())
        except Exception:
            healthy = False
        result.append({"name": name, "healthy": healthy})
    return result
```

In `src/workbench/main.py`:
- add `connections` to the `from workbench.api import (...)` import and `connections.router` to the include loop (and `messenger.router` when C1 lands).
- add `app.state.reload_lock = asyncio.Lock()` and `app.state.config_path` in lifespan; `import asyncio` at top.
- sync YAML `sources:` (with stable ids) into `source_configs` at startup so `get_sources()` returns them.

In lifespan, after `app.state.sources = create_providers_from_list(...)` and before building `db_sources`, insert the YAML->DB sync:

```python
    app.state.reload_lock = asyncio.Lock()
    app.state.config_path = os.environ.get("WORKBENCH_CONFIG", "config.yml")

    # Sync YAML sources (config.yml is source of truth) into source_configs.
    import uuid as _uuid
    from workbench.config_writer import write_source as _yaml_write_source
    from workbench.models import SourceConfig as _SourceConfig
    for raw in config.sources:
        sid = raw.get("id")
        if not sid:
            sid = str(_uuid.uuid4())
            node = dict(raw)
            node["id"] = sid
            _yaml_write_source(app.state.config_path, node)  # bump: writes stable id back
        sc = _SourceConfig(
            id=sid,
            adapter_type=raw.get("adapter_type", "unknown"),
            config=raw.get("config", {}),
            schedule=raw.get("schedule", "*/15 * * * *"),
            enabled=raw.get("enabled", True),
        )
        await app.state.stores.sources.upsert_source(sc)
```

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_sources_api.py tests/test_api.py -v`
Expected: PASS (update `test_api.py::test_sources_crud` per the note above so it uses `github`)

- [ ] Step 5: Commit
`git commit -am "feat(api): source CRUD with adapter allowlist, Config Write-Back + Targeted Hot-Reload, /api/connections"`

---

## PHASE C — Messenger, facts, triage backend

### Task C1: Messenger info/edit API + hot-swap
**Files:**
- Create `src/workbench/api/messenger.py`
- Modify `src/workbench/main.py` (register router)
- Test `tests/test_messenger_api.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_messenger_api.py
import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport


class _FakeMessenger:
    class _Cfg:
        space_id = "spaces/AAA"
        timeout_seconds = 5
        service_account_key_path = "/secret/sa.json"
    def __init__(self):
        self._config = self._Cfg()
    async def is_reachable(self):
        return True


@pytest.mark.asyncio
async def test_messenger_get_degraded_when_none(client, app_with_state):
    app_with_state.state.messenger = None
    r = await client.get("/api/messenger")
    assert r.status_code == 200
    assert r.json()["configured"] is False


@pytest.mark.asyncio
async def test_messenger_get_allowlisted_config_no_secret(client, app_with_state):
    app_with_state.state.messenger = _FakeMessenger()
    r = await client.get("/api/messenger")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is True
    assert data["config"]["space_id"] == "spaces/AAA"
    assert data["config"]["timeout_seconds"] == 5
    assert "service_account_key_path" not in data["config"]
    assert "/secret/sa.json" not in str(data)


@pytest.mark.asyncio
async def test_messenger_get_check_adds_reachability(client, app_with_state):
    app_with_state.state.messenger = _FakeMessenger()
    r = await client.get("/api/messenger?check=true")
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is True
    assert "checked_at" in data


@pytest.mark.asyncio
async def test_messenger_requires_auth(app_with_state):
    transport = ASGITransport(app=app_with_state)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/messenger")
        assert r.status_code == 401
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_messenger_api.py -v`
Expected: 404 on `/api/messenger`

- [ ] Step 3: Write minimal implementation

```python
# src/workbench/api/messenger.py
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from workbench.config_writer import write_messenger

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["messenger"])

# allowlist-on-output: only these config fields are ever serialized.
ALLOWED_CONFIG_FIELDS = ("space_id", "timeout_seconds")


def _allowlisted_config(messenger) -> dict:
    cfg = getattr(messenger, "_config", None)
    out = {}
    for field in ALLOWED_CONFIG_FIELDS:
        if cfg is not None and hasattr(cfg, field):
            out[field] = getattr(cfg, field)
    return out


@router.get("/messenger")
async def get_messenger(request: Request, check: bool = Query(False)):
    messenger = getattr(request.app.state, "messenger", None)
    if messenger is None:
        return {"configured": False, "type": None, "class": None, "config": {}}
    inner = getattr(messenger, "_inner", messenger)
    # Map the provider class to a short, stable type label (spec section 7.1).
    _MESSENGER_TYPES = {
        "GoogleChatMessenger": "google_chat",
        "ConsoleMessenger": "console",
    }
    data = {
        "configured": True,
        "type": _MESSENGER_TYPES.get(type(inner).__name__, type(inner).__name__),
        "class": type(inner).__qualname__,
        "config": _allowlisted_config(inner),
    }
    if check:
        reachable = False
        try:
            if hasattr(inner, "is_reachable"):
                reachable = bool(await inner.is_reachable())
        except Exception:
            reachable = False
        data["reachable"] = reachable
        data["checked_at"] = datetime.now(timezone.utc).isoformat()
    return data


class MessengerPatchBody(BaseModel):
    space_id: str | None = None
    timeout_seconds: int | None = None


@router.patch("/messenger")
async def patch_messenger(body: MessengerPatchBody, request: Request):
    import os
    config_path = getattr(request.app.state, "config_path", None) or os.environ.get("WORKBENCH_CONFIG", "config.yml")
    lock = request.app.state.reload_lock
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "No editable fields supplied")

    from workbench.registry import create_provider
    async with lock:
        write_messenger(config_path, patch)
        # rebuild messenger from the freshly written config
        new_config = request.app.state.config
        section = dict(new_config.messenger or {})
        section.update(patch)
        new_messenger = create_provider(section)
        request.app.state.messenger = new_messenger
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.messenger = new_messenger
            scheduler.alert_manager.messenger = new_messenger
    logger.info("messenger_updated", fields=list(patch.keys()))
    return {"status": "updated", "config": patch}
```

In `src/workbench/main.py`, add `messenger` to the `from workbench.api import (...)` block and `messenger.router` to the include loop.

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_messenger_api.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(api): GET/PATCH /api/messenger with allowlisted config + hot-swap rebind"`

---

### Task C2: Facts envelope + Fact model id/timestamp + Fact Curation endpoints
**Files:**
- Modify `src/workbench/models.py` (`Fact.id`, `Fact.timestamp`)
- Modify `src/workbench/memory/base.py` (`delete_fact`/`update_fact`/`list_facts`)
- Modify `src/workbench/memory/noop.py` (501 raisers + list_facts)
- Modify `src/workbench/memory/http.py` (impls + fix timestamp population)
- Modify `src/workbench/api/memory.py` (envelope + curation routes)
- Test `tests/test_memory_api.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_memory_api.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from workbench.models import Fact


@pytest.mark.asyncio
async def test_facts_envelope_noop(client, app_with_state):
    r = await client.get("/api/memory/facts")
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is False
    assert data["memory_type"] == "noop"
    assert data["facts"] == []


@pytest.mark.asyncio
async def test_facts_envelope_available(client, app_with_state):
    mem = AsyncMock()
    mem.is_available.return_value = True
    mem.list_facts.return_value = [
        Fact(id="f1", content="user prioritizes blocked PRs", source="interaction",
             timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ]
    mem.memory_type = "zep"
    app_with_state.state.memory = mem
    r = await client.get("/api/memory/facts")
    data = r.json()
    assert data["available"] is True
    assert data["memory_type"] == "zep"
    assert data["facts"][0]["id"] == "f1"
    assert data["facts"][0]["timestamp"].startswith("2026-06-01")


@pytest.mark.asyncio
async def test_delete_fact_501_under_noop(client, app_with_state):
    r = await client.delete("/api/memory/facts/abc")
    assert r.status_code == 501


@pytest.mark.asyncio
async def test_patch_fact_501_under_noop(client, app_with_state):
    r = await client.patch("/api/memory/facts/abc", json={"content": "new"})
    assert r.status_code == 501


@pytest.mark.asyncio
async def test_delete_fact_success(client, app_with_state):
    mem = AsyncMock()
    mem.delete_fact.return_value = None
    app_with_state.state.memory = mem
    r = await client.delete("/api/memory/facts/f1")
    assert r.status_code == 200
    mem.delete_fact.assert_awaited_once_with("f1")


@pytest.mark.asyncio
async def test_patch_fact_success(client, app_with_state):
    mem = AsyncMock()
    mem.update_fact.return_value = None
    app_with_state.state.memory = mem
    r = await client.patch("/api/memory/facts/f1", json={"content": "edited"})
    assert r.status_code == 200
    mem.update_fact.assert_awaited_once_with("f1", "edited")
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_memory_api.py -v`
Expected: first test fails — `/api/memory/facts` returns a bare list, not an envelope.

- [ ] Step 3: Write minimal implementation

In `src/workbench/models.py`, update `Fact`:

```python
class Fact(BaseModel):
    id: str = ""
    content: str
    source: str = ""
    timestamp: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
```

In `src/workbench/memory/base.py`, add abstract methods + a `memory_type` hook with a default:

```python
class MemoryLayer(ABC):
    memory_type: str = "unknown"

    # ... existing abstract methods ...

    @abstractmethod
    async def delete_fact(self, fact_id: str) -> None: ...
    @abstractmethod
    async def update_fact(self, fact_id: str, content: str) -> None: ...
    @abstractmethod
    async def list_facts(self) -> list["Fact"]: ...
```

(Import `Fact` is already present at the top of `base.py`.)

In `src/workbench/memory/noop.py`, add:

```python
    memory_type = "noop"

    async def delete_fact(self, fact_id):
        raise NotImplementedError("NoopMemoryLayer does not support fact curation")

    async def update_fact(self, fact_id, content):
        raise NotImplementedError("NoopMemoryLayer does not support fact curation")

    async def list_facts(self):
        return []
```

In `src/workbench/memory/http.py`, set `memory_type` and add the methods; also fix `query_preferences` to populate `id`+`timestamp` and implement `list_facts`:

```python
class HttpMemoryLayer(MemoryLayer):
    memory_type = "zep"
    # ... existing ProviderConfig + __init__ ...
```

Fix `query_preferences` return mapping:

```python
            return [
                Fact(
                    id=f.get("id", ""),
                    content=f["content"],
                    source=f.get("source", "graphiti"),
                    timestamp=datetime.fromisoformat(f["timestamp"]) if f.get("timestamp") else None,
                )
                for f in data.get("facts", [])
            ]
```

(Add `from datetime import datetime` to the imports.)

Add new methods:

```python
    async def list_facts(self) -> list[Fact]:
        try:
            resp = await self._client.get(f"{self._base_url}/facts")
            resp.raise_for_status()
            data = resp.json()
            return [
                Fact(
                    id=f.get("id", ""),
                    content=f["content"],
                    source=f.get("source", "graphiti"),
                    timestamp=datetime.fromisoformat(f["timestamp"]) if f.get("timestamp") else None,
                )
                for f in data.get("facts", [])
            ]
        except Exception as e:
            logger.warning("Memory service list_facts failed: %s", e)
            return []

    async def delete_fact(self, fact_id: str) -> None:
        resp = await self._client.delete(f"{self._base_url}/facts/{fact_id}")
        resp.raise_for_status()

    async def update_fact(self, fact_id: str, content: str) -> None:
        resp = await self._client.patch(
            f"{self._base_url}/facts/{fact_id}", json={"content": content}
        )
        resp.raise_for_status()
```

Replace `src/workbench/api/memory.py` entirely:

```python
# src/workbench/api/memory.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory/facts")
async def get_facts(request: Request):
    """Returns the facts envelope {available, memory_type, facts}."""
    memory = request.app.state.memory
    memory_type = getattr(memory, "memory_type", "unknown")
    try:
        available = await memory.is_available()
    except Exception:
        available = False
    facts = []
    if available:
        try:
            facts = await memory.list_facts()
        except Exception:
            facts = []
    return {
        "available": available,
        "memory_type": memory_type,
        "facts": [f.model_dump(mode="json") for f in facts],
    }


@router.delete("/memory/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request):
    memory = request.app.state.memory
    try:
        await memory.delete_fact(fact_id)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    return {"status": "deleted"}


class FactPatchBody(BaseModel):
    content: str


@router.patch("/memory/facts/{fact_id}")
async def update_fact(fact_id: str, body: FactPatchBody, request: Request):
    memory = request.app.state.memory
    try:
        await memory.update_fact(fact_id, body.content)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    return {"status": "updated"}
```

> Existing `tests/test_api.py::test_memory_facts_empty` asserts the bare-list shape. Update it to assert the envelope:
> ```python
> r = await client.get("/api/memory/facts")
> assert r.status_code == 200
> body = r.json()
> assert body == {"available": False, "memory_type": "noop", "facts": []}
> ```

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_memory_api.py tests/test_api.py::test_memory_facts_empty -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(memory): facts envelope + Fact id/timestamp + curation endpoints (501 under Noop)"`

---

### Task C3: Triage web-respond 409 guard + confirm + audit-gap fix
**Files:**
- Modify `src/workbench/api/triage.py`
- Modify `src/workbench/pipeline/scheduler.py` (`_execute_interpreted_response` early-return audit log)
- Test `tests/test_triage_web.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_triage_web.py
import pytest
from unittest.mock import AsyncMock
from workbench.models import (
    TriageCard, TriageOption, InterpretedResponse, SystemAction, UserTodo,
)


@pytest.mark.asyncio
async def test_respond_409_on_already_responded(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="responded",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "choice": 1})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_respond_409_on_expired(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="expired",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "choice": 1})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_destructive_free_text_returns_awaiting_confirmation(client, app_with_state):
    stores = app_with_state.state.stores
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github"},
        options=[TriageOption(label="Skip", action="skip")],
        status="sent",
    )
    await stores.triage.save_card(card)
    llm = AsyncMock()
    llm.interpret_triage_response.return_value = InterpretedResponse(
        system_actions=[SystemAction(action="skip")], explanation="will skip",
    )
    app_with_state.state.llm = llm
    r = await client.post("/api/triage/respond", json={"card_id": card.id, "raw_text": "drop it"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "awaiting_confirmation"
    assert data["explanation"] == "will skip"
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "awaiting_confirmation"
    # audit gap closed: an InteractionEntry exists for the destructive-pending branch
    entries = await stores.interactions.get_all()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_confirm_executes_destructive(client, app_with_state):
    stores = app_with_state.state.stores
    interpreted = InterpretedResponse(system_actions=[SystemAction(action="skip")], explanation="skip")
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github",
                      "pending_interpreted": interpreted.model_dump()},
        options=[TriageOption(label="Skip", action="skip")],
        status="awaiting_confirmation",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/confirm", json={"card_id": card.id, "confirm": True})
    assert r.status_code == 200
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "responded"


@pytest.mark.asyncio
async def test_confirm_cancel_returns_card_to_sent(client, app_with_state):
    stores = app_with_state.state.stores
    interpreted = InterpretedResponse(system_actions=[SystemAction(action="skip")], explanation="skip")
    card = TriageCard(
        card_content={"summary": "x", "source_type": "github",
                      "pending_interpreted": interpreted.model_dump()},
        options=[TriageOption(label="Skip", action="skip")],
        status="awaiting_confirmation",
    )
    await stores.triage.save_card(card)
    r = await client.post("/api/triage/confirm", json={"card_id": card.id, "confirm": False})
    assert r.status_code == 200
    refreshed = await stores.triage.get_card(card.id)
    assert refreshed.status == "sent"
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_triage_web.py -v`
Expected: `test_respond_409_on_already_responded` fails (returns 200, not 409).

- [ ] Step 3: Write minimal implementation

In `src/workbench/api/triage.py`, add the 409 guard immediately after the `if not card:` check in `respond_to_triage`:

```python
    if card.status in ("responded", "expired"):
        raise HTTPException(409, f"Card already {card.status}")
```

Change the free-text branch so the API returns the scheduler's followup status (awaiting_confirmation) rather than always "interpreted". Replace the free-text block:

```python
    if response.choice is None and response.raw_text:
        llm = getattr(request.app.state, "llm", None)
        if not llm:
            raise HTTPException(503, "LLM provider not configured for free-text interpretation")
        interpreted = await llm.interpret_triage_response(card, response.raw_text)
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is None:
            raise HTTPException(503, "Scheduler not available")
        await scheduler._execute_interpreted_response(interpreted, card)
        refreshed = await stores.triage.get_card(card.id)
        if refreshed and refreshed.status == "awaiting_confirmation":
            return {
                "status": "awaiting_confirmation",
                "explanation": interpreted.explanation,
                "card_id": card.id,
            }
        return TriageResponseResult(
            status="interpreted", action="free_text",
            system_actions_executed=[a.action for a in interpreted.system_actions],
            user_todos_created=[t.summary for t in interpreted.user_todos],
            explanation=interpreted.explanation,
        )
```

Add the confirm endpoint at the end of `triage.py`:

```python
class ConfirmBody(BaseModel):
    card_id: str
    confirm: bool


@router.post("/triage/confirm")
async def confirm_triage(body: ConfirmBody, request: Request):
    stores = request.app.state.stores
    card = await stores.triage.get_card(body.card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")
    if card.status != "awaiting_confirmation":
        raise HTTPException(409, f"Card is not awaiting confirmation (status={card.status})")
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(503, "Scheduler not available")
    text = "yes" if body.confirm else "no"
    await scheduler._handle_confirmation(card, text)
    refreshed = await stores.triage.get_card(card.id)
    return {"status": refreshed.status}
```

Add `from pydantic import BaseModel` to the imports of `triage.py`.

Close the audit gap in `src/workbench/pipeline/scheduler.py`'s `_execute_interpreted_response`: the destructive-pending branch and the defer branch return early without an `InteractionEntry`. In the destructive branch (the `if action.action in ("skip", "mute_pattern"):` block), before `return`, append an entry:

```python
                entry = InteractionEntry(
                    source_type=card.card_content.get("source_type", "unknown"),
                    item_id=card.item_id,
                    item_summary=card.card_content.get("summary", ""),
                    triage_card_full=card.card_content,
                    options_presented=[o.model_dump() for o in card.options],
                    option_chosen="free_text_pending_confirmation",
                    type="free_text",
                    interpreted=interpreted.model_dump(),
                )
                await self.stores.interactions.append(entry)
                return
```

In the defer branch (`elif action.action == "defer":`), before its `return`, append:

```python
                entry = InteractionEntry(
                    source_type=card.card_content.get("source_type", "unknown"),
                    item_id=card.item_id,
                    item_summary=card.card_content.get("summary", ""),
                    triage_card_full=card.card_content,
                    options_presented=[o.model_dump() for o in card.options],
                    option_chosen="free_text_deferred",
                    type="free_text",
                    interpreted=interpreted.model_dump(),
                )
                await self.stores.interactions.append(entry)
                return
```

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_triage_web.py tests/test_api.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(triage): 409 double-response guard, /api/triage/confirm, close interaction-log audit gap"`

---

### Task C4 (STUB — workbench-meta, labeled): memory-service Graphiti fact-curation endpoints
**Files:** workbench-meta memory-service (separate repo `~/workspace/workbench-meta/`)

This task is NOT implemented in this repo. It is a clearly-labeled stub referencing ADR 0019.
The Graphiti-backed memory service in workbench-meta must add:
- `DELETE /facts/{id}` — writes a tombstone so the fact is not re-synthesized from the Interaction Log.
- `PATCH /facts/{id}` — updates content + writes a negative-preference marker for the prior content.
- `GET /facts` — list-all contract returning `{facts:[{id, content, source, timestamp}]}` with service-assigned ids and populated timestamps.
Fact Curation is recorded via ordinary structured app logging, deliberately NOT in the Interaction Log.
Track this as a Meta Task with `--owner=anshulverma`. No commit in this repo.

---

## PHASE D — Frontend scaffold

### Task D1: Upgrade deps + migrate to Tailwind v4 (CSS-first)
**Files:**
- Modify `ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/src/index.css`
- Delete `ui/tailwind.config.js`, `ui/postcss.config.js`
- Verification: `cd ui && npm run build`

- [ ] Step 1: Write the failing test
This task's "test" is a successful build. First confirm the current build fails after we rewrite `index.css` to v4 syntax without the v4 toolchain. (No vitest yet — vitest is added in D2.)
Run (baseline): `cd ui && npm run build`
Expected baseline: succeeds on the old v3 stack (do not commit). We will replace the stack.

- [ ] Step 2: Run to verify it fails
Run: `cd ui && rm -f tailwind.config.js postcss.config.js && npm run build`
Expected: build fails — Tailwind v3 PostCSS pipeline gone, `@tailwindcss/vite` not yet installed (`Cannot find module '@tailwindcss/vite'` or unknown `@theme` at-rule).

- [ ] Step 3: Write minimal implementation

Replace `ui/package.json`:

```json
{
  "name": "workbench-ui",
  "private": true,
  "version": "0.2.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "gen:api": "openapi-typescript http://127.0.0.1:8421/openapi.json -o src/lib/api-types.ts"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "cron-parser": "^4.9.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-hook-form": "^7.53.0",
    "react-router-dom": "^7.0.0",
    "recharts": "^3.0.0",
    "sonner": "^1.7.0",
    "zod": "^4.0.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.0",
    "msw": "^2.6.0",
    "openapi-typescript": "^7.4.0",
    "tailwindcss": "^4.0.0",
    "tw-animate-css": "^1.0.0",
    "typescript": "^5.6.3",
    "vite": "^7.0.0",
    "vitest": "^3.0.0"
  }
}
```

> `cron-parser` (pinned `^4.9.0`) is added for the client-side next-run preview in the Sources schedule controls (Task E3c). It parses a cron expression and yields the next fire time without a backend round-trip.

Replace `ui/vite.config.ts`:

```ts
// ui/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/ui/',
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  build: { outDir: 'dist' },
  server: {
    proxy: { '/api': 'http://localhost:8421' },
  },
})
```

Replace `ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"]
}
```

Replace `ui/src/index.css` (Tailwind v4 CSS-first, dark-by-default tokens):

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.145 0 0);
  --primary: oklch(0.205 0 0);
  --primary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);
  --border: oklch(0.922 0 0);
  --ring: oklch(0.708 0 0);
  --destructive: oklch(0.577 0.245 27.325);
}

.dark {
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.205 0 0);
  --card-foreground: oklch(0.985 0 0);
  --primary: oklch(0.985 0 0);
  --primary-foreground: oklch(0.205 0 0);
  --muted: oklch(0.269 0 0);
  --muted-foreground: oklch(0.708 0 0);
  --border: oklch(1 0 0 / 10%);
  --ring: oklch(0.556 0 0);
  --destructive: oklch(0.704 0.191 22.216);
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-border: var(--border);
  --color-ring: var(--ring);
  --color-destructive: var(--destructive);
}

body {
  background-color: var(--background);
  color: var(--foreground);
}
```

In `ui/index.html`, set the root `<html>` to dark by default: `<html lang="en" class="dark">`.

- [ ] Step 4: Run to verify it passes
Run: `cd ui && npm install && npm run build`
Expected: build succeeds; `dist/` produced; `tailwind.config.js` and `postcss.config.js` absent.

- [ ] Step 5: Commit
`git commit -am "build(ui): React 19 + Vite 7 + Tailwind v4 CSS-first; drop postcss/autoprefixer; add @/ alias"`

---

### Task D2: shadcn/ui base + providers + shared primitives + api client + gen:api
**Files:**
- Create `ui/components.json`, `ui/vitest.config.ts`, `ui/src/test/setup.ts`, `ui/src/test/server.ts`
- Create `ui/src/components/ui/*` (shadcn: button, card, table, dialog, form, switch, select, skeleton, sonner)
- Create `ui/src/lib/query-client.ts`, `ui/src/lib/format.ts`
- Move `ui/src/api.ts` -> `ui/src/lib/api.ts` (fix docstring, surface X-Request-ID)
- Create `ui/src/components/{ErrorBoundary,EmptyState,StatCard,DataTable,ChartCard,HealthBadge,AppShell,AppSidebar}.tsx`
- Modify `ui/src/main.tsx`, `ui/src/App.tsx`
- Create committed `ui/src/lib/api-types.ts` via `npm run gen:api`
- Test `ui/src/lib/api.test.ts`

- [ ] Step 1: Write the failing test

```ts
// ui/src/lib/api.test.ts
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { apiGet, ApiError, _resetToken } from './api'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
)

beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

describe('api client', () => {
  it('attaches bearer token from the token-vending endpoint', async () => {
    let seen = ''
    server.use(
      http.get('/api/stats/overview', ({ request }) => {
        seen = request.headers.get('Authorization') ?? ''
        return HttpResponse.json({ pending_triage: 0 })
      }),
    )
    const data = await apiGet<{ pending_triage: number }>('/api/stats/overview')
    expect(seen).toBe('Bearer tok-123')
    expect(data.pending_triage).toBe(0)
  })

  it('throws ApiError carrying the X-Request-ID on failure', async () => {
    server.use(
      http.get('/api/stats/overview', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500, headers: { 'X-Request-ID': 'req-9' } }),
      ),
    )
    await expect(apiGet('/api/stats/overview')).rejects.toMatchObject({
      status: 500,
      requestId: 'req-9',
    })
  })

  it('throws ApiError with status 401 when token endpoint is unauthorized', async () => {
    server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
    await expect(apiGet('/api/stats/overview')).rejects.toMatchObject({ status: 401 })
  })
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/lib/api.test.ts`
Expected: fails to resolve `./api` exports `apiGet`/`ApiError`/`_resetToken` (or no vitest config).

- [ ] Step 3: Write minimal implementation

```ts
// ui/vitest.config.ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

```ts
// ui/src/test/setup.ts
import '@testing-library/jest-dom/vitest'
```

```ts
// ui/src/test/server.ts
import { setupServer } from 'msw/node'
export const server = setupServer()
```

```ts
// ui/src/lib/api.ts
// getToken(): GET /api/auth/token (the Token-Vending Endpoint) returns
// { token }. The endpoint is auth-exempt and same-origin; safe only under
// loopback/SSH-tunnel isolation. The token is held in module memory for the
// page session and attached as Authorization: Bearer to every /api call.

let _token: string | null = null

export function _resetToken() {
  _token = null
}

export class ApiError extends Error {
  status: number
  requestId: string | null
  constructor(message: string, status: number, requestId: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.requestId = requestId
  }
}

async function getToken(): Promise<string> {
  if (_token) return _token
  const res = await fetch('/api/auth/token')
  if (!res.ok) {
    throw new ApiError('token unavailable', res.status, res.headers.get('X-Request-ID'))
  }
  const data = await res.json()
  _token = data.token
  return _token!
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    ...(await authHeaders()),
    ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  }
  const res = await fetch(path, { ...init, headers })
  const requestId = res.headers.get('X-Request-ID')
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ? JSON.stringify(body.detail) : detail
    } catch {
      /* non-json error body */
    }
    throw new ApiError(detail, res.status, requestId)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const apiGet = <T>(path: string) => request<T>(path)
export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
export const apiPatch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined })
export const apiDelete = <T>(path: string) => request<T>(path, { method: 'DELETE' })
```

```ts
// ui/src/lib/query-client.ts
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchIntervalInBackground: false,
      retry: 1,
    },
  },
})

// Pause polling on a hidden tab: refetchInterval functions read this.
export function pollWhenVisible(ms: number) {
  return () => (document.visibilityState === 'visible' ? ms : false)
}
```

```ts
// ui/src/lib/format.ts
export function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const diff = Date.now() - then
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}
```

Initialize shadcn/ui and add base components:

```bash
cd ui && npx shadcn@latest init -d
cd ui && npx shadcn@latest add button card table dialog dropdown-menu form switch select skeleton sonner
```

This generates `ui/components.json` and `ui/src/components/ui/*`. Confirm `components.json` uses CSS variables and the `@/*` alias.

Shared primitives:

```tsx
// ui/src/components/EmptyState.tsx
import type { ReactNode } from 'react'

export function EmptyState({ message, cta }: { message: string; cta?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-10 text-muted-foreground">
      <p>{message}</p>
      {cta}
    </div>
  )
}
```

```tsx
// ui/src/components/HealthBadge.tsx
const COLORS: Record<string, string> = {
  healthy: 'bg-green-600',
  never_run: 'bg-gray-500',
  erroring: 'bg-red-600',
  disabled: 'bg-gray-400',
  configured: 'bg-green-600',
  'not-configured': 'bg-amber-600',
}

export function HealthBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs text-white ${COLORS[status] ?? 'bg-gray-500'}`}>
      {status}
    </span>
  )
}
```

```tsx
// ui/src/components/StatCard.tsx
import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function StatCard({ label, value, danger }: { label: string; value: ReactNode; danger?: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${danger ? 'text-destructive' : ''}`}>{value}</div>
      </CardContent>
    </Card>
  )
}
```

```tsx
// ui/src/components/ErrorBoundary.tsx
import { Component, type ReactNode } from 'react'

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      const requestId = (this.state.error as { requestId?: string }).requestId
      return (
        <div role="alert" className="p-6 text-destructive">
          <p>Something went wrong: {this.state.error.message}</p>
          {requestId && <p className="text-xs">Request ID: {requestId}</p>}
        </div>
      )
    }
    return this.props.children
  }
}
```

```tsx
// ui/src/components/ChartCard.tsx
import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function ChartCard({ title, children, empty }: { title: string; children: ReactNode; empty?: boolean }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent className="h-64">
        {empty ? <p className="text-muted-foreground text-sm">No data yet</p> : children}
      </CardContent>
    </Card>
  )
}
```

```tsx
// ui/src/components/DataTable.tsx
import type { ReactNode } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
}

export function DataTable<T>({ columns, rows, rowKey }: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>{columns.map((c) => <TableHead key={c.key}>{c.header}</TableHead>)}</TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={rowKey(row)}>
            {columns.map((c) => <TableCell key={c.key}>{c.render(row)}</TableCell>)}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

```tsx
// ui/src/components/AppSidebar.tsx
import { NavLink } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/triage', label: 'Triage' },
  { to: '/actions', label: 'Action Items' },
  { to: '/ingestion', label: 'Ingestion' },
  { to: '/sources', label: 'Sources' },
  { to: '/knowledge', label: 'Knowledge' },
  { to: '/messenger', label: 'Messenger' },
  { to: '/settings', label: 'Settings' },
]

export function AppSidebar() {
  return (
    <nav aria-label="Primary" className="w-52 shrink-0 border-r border-border p-3">
      <h1 className="mb-4 px-2 text-lg font-bold">Workbench</h1>
      <ul className="space-y-1">
        {NAV.map((n) => (
          <li key={n.to}>
            <NavLink
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `block rounded px-2 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${
                  isActive ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted'
                }`
              }
            >
              {n.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
```

```tsx
// ui/src/components/AppShell.tsx
import type { ReactNode } from 'react'
import { AppSidebar } from './AppSidebar'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 p-6">{children}</main>
    </div>
  )
}
```

```tsx
// ui/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { HashRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { queryClient } from '@/lib/query-client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
        <Toaster />
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
```

```tsx
// ui/src/App.tsx
import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Overview } from '@/pages/Overview'
import { Triage } from '@/pages/Triage'
import { ActionItems } from '@/pages/ActionItems'
import { Ingestion } from '@/pages/Ingestion'
import { Sources } from '@/pages/Sources'
import { Knowledge } from '@/pages/Knowledge'
import { Messenger } from '@/pages/Messenger'
import { Settings } from '@/pages/Settings'

export default function App() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/triage" element={<Triage />} />
          <Route path="/actions" element={<ActionItems />} />
          <Route path="/ingestion" element={<Ingestion />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/messenger" element={<Messenger />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}
```

> The page imports above reference files created in Phase E. To keep `npm run build` green at the end of D2, create minimal placeholder page components now (each `export function NAME() { return <div /> }`) and flesh them out in Phase E. Replace, do not cross-reference. The existing `ui/src/components/ActionList.tsx` is preserved and re-used by `ActionItems` in Task E7.

Generate committed API types (server must be running locally at `127.0.0.1:8421`):

```bash
cd ui && npm run gen:api
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/lib/api.test.ts && npm run build`
Expected: PASS (api.test.ts green) and build succeeds.

- [ ] Step 5: Commit
`git commit -am "feat(ui): shadcn base, TanStack Query + HashRouter shell, shared primitives, typed api client, gen:api"`

---

## PHASE E — Frontend pages (Vitest + RTL + MSW)

Each page implements the five UI State Taxonomy states. Each page test file mounts the page inside a fresh `QueryClientProvider` + `MemoryRouter` with MSW handlers. The shared render helper below is created once and imported by all page tests.

```tsx
// ui/src/test/render.tsx
import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

export function renderPage(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}
```

### Task E1: Overview page
**Files:**
- Create `ui/src/hooks/useStats.ts`
- Create `ui/src/pages/Overview.tsx`
- Test `ui/src/pages/Overview.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Overview.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Overview } from './Overview'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function overview(partial = {}) {
  return {
    pending_triage: 2, in_flight: 1, dead_letters: 0, active_items: 5,
    sources_enabled: 1, sources_total: 2,
    items: { by_status: { active: 5 }, by_priority: { P0: 1 }, by_category: { action_item: 3 }, by_source: { github: 5 } },
    ...partial,
  }
}

it('loading state renders skeletons', () => {
  server.use(http.get('/api/stats/overview', () => new Promise(() => {})))
  renderPage(<Overview />)
  expect(screen.getByTestId('overview-loading')).toBeInTheDocument()
})

it('happy path renders the six stat cards', async () => {
  server.use(
    http.get('/api/stats/overview', () => HttpResponse.json(overview())),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  expect(await screen.findByText('Pending triage')).toBeInTheDocument()
  expect(screen.getByText('Dead letters')).toBeInTheDocument()
})

it('renders all four spec charts', async () => {
  server.use(
    http.get('/api/stats/overview', () => HttpResponse.json(overview())),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([{ bucket_ts: '2026-06-01', raw_enqueued: 4 }])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  expect(await screen.findByText('Ingestion (14d)')).toBeInTheDocument()
  expect(screen.getByText('Items by priority')).toBeInTheDocument()
  expect(screen.getByText('Items by source')).toBeInTheDocument()
  expect(screen.getByText('Items by category')).toBeInTheDocument()
})

it('renders the messenger HealthBadge from /api/messenger', async () => {
  server.use(
    http.get('/api/stats/overview', () => HttpResponse.json(overview())),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: false, type: null, class: null, config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  expect(await screen.findByText('Messenger')).toBeInTheDocument()
  expect(await screen.findByText('not-configured')).toBeInTheDocument()
})

it('shows the dead-letter banner when dead_letters > 0', async () => {
  server.use(
    http.get('/api/stats/overview', () => HttpResponse.json(overview({ dead_letters: 3 }))),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  expect(await screen.findByRole('alert')).toHaveTextContent(/dead.?letter/i)
})

it('empty state when all counts are zero', async () => {
  server.use(
    http.get('/api/stats/overview', () => HttpResponse.json(overview({
      pending_triage: 0, in_flight: 0, dead_letters: 0, active_items: 0,
      sources_enabled: 0, sources_total: 0,
    }))),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: false, type: null, class: null, config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  expect(await screen.findByText(/No activity yet/i)).toBeInTheDocument()
})

it('error state surfaces the request id', async () => {
  server.use(
    http.get('/api/stats/overview', () =>
      HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-1' } })),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  await waitFor(() => expect(screen.getByText(/req-1/)).toBeInTheDocument())
})

it('unauthorized state when token endpoint 401s', async () => {
  server.use(
    http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
    http.get('/api/stats/overview', () => HttpResponse.json(overview())),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json([])),
    http.get('/api/jobs', () => HttpResponse.json({ jobs: [], total: 0 })),
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: {} })),
    http.get('/health', () => HttpResponse.json({ status: 'healthy' })),
  )
  renderPage(<Overview />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Overview.test.tsx`
Expected: fails — `./Overview` has no real export (placeholder), assertions miss.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useStats.ts
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface Overview {
  pending_triage: number
  in_flight: number
  dead_letters: number
  active_items: number
  sources_enabled: number
  sources_total: number
  items: {
    by_status: Record<string, number>
    by_priority: Record<string, number>
    by_category: Record<string, number>
    by_source: Record<string, number>
  }
}

export function useStatsOverview() {
  return useQuery({
    queryKey: ['stats', 'overview'],
    queryFn: () => apiGet<Overview>('/api/stats/overview'),
    refetchInterval: pollWhenVisible(15_000),
  })
}

export function useIngestionTimeseries(days = 14) {
  return useQuery({
    queryKey: ['stats', 'ingestion-timeseries', days],
    queryFn: () => apiGet<{ bucket_ts: string; raw_enqueued: number }[]>(
      `/api/stats/ingestion-timeseries?days=${days}&bucket=day`,
    ),
  })
}

export function useRecentJobs(limit = 10) {
  return useQuery({
    queryKey: ['jobs', { limit }],
    queryFn: () => apiGet<{ jobs: unknown[]; total: number }>(`/api/jobs?limit=${limit}`),
  })
}

export interface MessengerStatus {
  configured: boolean
  type: string | null
  class: string | null
  config: Record<string, unknown>
  reachable?: boolean
  checked_at?: string
}

export function useMessengerStatus() {
  return useQuery({
    queryKey: ['messenger'],
    queryFn: () => apiGet<MessengerStatus>('/api/messenger'),
  })
}
```

```tsx
// ui/src/pages/Overview.tsx
import { Link } from 'react-router-dom'
import {
  Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis,
} from 'recharts'
import { useStatsOverview, useIngestionTimeseries, useMessengerStatus } from '@/hooks/useStats'
import { StatCard } from '@/components/StatCard'
import { ChartCard } from '@/components/ChartCard'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

const DONUT_COLORS = ['#16a34a', '#2563eb', '#d97706', '#dc2626', '#7c3aed', '#0891b2']
const CATEGORY_ORDER = ['action_item', 'meeting', 'plan_seed', 'informational']

export function Overview() {
  const stats = useStatsOverview()
  const ts = useIngestionTimeseries(14)
  const messenger = useMessengerStatus()

  if (stats.isPending) {
    return (
      <div data-testid="overview-loading" className="grid grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
    )
  }

  if (stats.isError) {
    const err = stats.error as ApiError
    if (err.status === 401) {
      return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load overview: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const o = stats.data
  const allZero =
    o.pending_triage === 0 && o.in_flight === 0 && o.dead_letters === 0 &&
    o.active_items === 0 && o.sources_total === 0

  if (allZero) {
    return (
      <EmptyState
        message="No activity yet — add a source to begin"
        cta={<Link to="/sources" className="underline">Go to Sources</Link>}
      />
    )
  }

  const priorityData = Object.entries(o.items.by_priority).map(([k, v]) => ({ name: k, value: v }))
  const sourceData = Object.entries(o.items.by_source).map(([k, v]) => ({ name: k, value: v }))
  const categoryData = CATEGORY_ORDER.map((name) => ({ name, value: o.items.by_category[name] ?? 0 }))
  const messengerStatus = messenger.data
    ? (messenger.data.configured ? 'configured' : 'not-configured')
    : 'never_run'

  return (
    <div className="space-y-6">
      {o.dead_letters > 0 && (
        <div role="alert" className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {o.dead_letters} dead-letter entries need investigation.{' '}
          <Link to="/ingestion" className="underline">View</Link>
        </div>
      )}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Pending triage" value={o.pending_triage} />
        <StatCard label="In flight" value={o.in_flight} />
        <StatCard label="Dead letters" value={o.dead_letters} danger={o.dead_letters > 0} />
        <StatCard label="Active items" value={o.active_items} />
        <StatCard label="Sources" value={`${o.sources_enabled}/${o.sources_total}`} />
        <StatCard label="Messenger" value={<HealthBadge status={messengerStatus} />} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ChartCard title="Ingestion (14d)" empty={!ts.data || ts.data.length === 0}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={ts.data ?? []}>
              <XAxis dataKey="bucket_ts" hide />
              <Tooltip />
              <Area dataKey="raw_enqueued" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Items by priority" empty={priorityData.length === 0}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={priorityData}>
              <XAxis dataKey="name" />
              <Tooltip />
              <Bar dataKey="value" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Items by source" empty={sourceData.length === 0}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip />
              <Pie data={sourceData} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="80%">
                {sourceData.map((_, i) => <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Items by category" empty={categoryData.every((d) => d.value === 0)}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={categoryData}>
              <XAxis dataKey="name" />
              <Tooltip />
              <Bar dataKey="value" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Overview.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Overview page with stat cards, charts, dead-letter banner, five-state handling"`

---

### Task E2: Ingestion page
**Files:**
- Create `ui/src/hooks/useIngestion.ts`
- Create `ui/src/pages/Ingestion.tsx`
- Test `ui/src/pages/Ingestion.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Ingestion.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Ingestion } from './Ingestion'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const sourcesRow = {
  id: 's1', adapter_type: 'github', enabled: true, schedule: '*/15 * * * *',
  last_run: '2026-06-04T00:00:00Z', items_stored: 12, raw_enqueued: 3, in_flight: 3,
  health_status: 'healthy',
}

function baseHandlers(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('/api/stats/sources', () => HttpResponse.json(overrides.sources ?? [sourcesRow])),
    http.get('/api/activity', () => HttpResponse.json(overrides.activity ?? [])),
    http.get('/api/jobs', () => HttpResponse.json(overrides.jobs ?? { jobs: [], total: 0 })),
    http.get('/api/stats/queue', () => HttpResponse.json(overrides.queue ?? { queued: 0, processing: 0, dead_letter: 0 })),
    http.get('/api/queue/dead-letter', () => HttpResponse.json(overrides.dl ?? [])),
  )
}

it('loading state renders skeleton', () => {
  server.use(http.get('/api/stats/sources', () => new Promise(() => {})))
  renderPage(<Ingestion />)
  expect(screen.getByTestId('ingestion-loading')).toBeInTheDocument()
})

it('happy path shows qualified ingested counts', async () => {
  baseHandlers()
  renderPage(<Ingestion />)
  expect(await screen.findByText(/items_stored/i)).toBeInTheDocument()
  expect(screen.getByText('12')).toBeInTheDocument()
})

it('empty state when no sources', async () => {
  baseHandlers({ sources: [] })
  renderPage(<Ingestion />)
  expect(await screen.findByText(/No ingestion runs yet/i)).toBeInTheDocument()
})

it('error state surfaces request id', async () => {
  server.use(
    http.get('/api/stats/sources', () =>
      HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-7' } })),
  )
  renderPage(<Ingestion />)
  await waitFor(() => expect(screen.getByText(/req-7/)).toBeInTheDocument())
})

it('unauthorized state', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  baseHandlers()
  renderPage(<Ingestion />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})

it('dead-letter retry mutation (happy path) invalidates', async () => {
  let retried = false
  baseHandlers({ dl: [{ id: 'd1', source_type: 'github', error: 'boom' }] })
  server.use(
    http.post('/api/queue/dead-letter/d1/retry', () => { retried = true; return HttpResponse.json({ status: 'requeued' }) }),
  )
  renderPage(<Ingestion />)
  const btn = await screen.findByRole('button', { name: /retry/i })
  await userEvent.click(btn)
  await waitFor(() => expect(retried).toBe(true))
})

it('dead-letter retry failure surfaces error toast text', async () => {
  baseHandlers({ dl: [{ id: 'd1', source_type: 'github', error: 'boom' }] })
  server.use(
    http.post('/api/queue/dead-letter/d1/retry', () =>
      HttpResponse.json({ detail: 'nope' }, { status: 500, headers: { 'X-Request-ID': 'req-x' } })),
  )
  renderPage(<Ingestion />)
  const btn = await screen.findByRole('button', { name: /retry/i })
  await userEvent.click(btn)
  await waitFor(() => expect(screen.getByText(/retry failed/i)).toBeInTheDocument())
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Ingestion.test.tsx`
Expected: fails — placeholder `Ingestion` has no real content.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useIngestion.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiDelete } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface SourceStat {
  id: string; adapter_type: string; enabled: boolean; schedule: string
  last_run: string | null; items_stored: number; raw_enqueued: number; in_flight: number
  health_status: string
  // present on /api/stats/sources rows so the edit form can prefill type-specific fields;
  // optional so the kebab Edit action degrades to an empty form when absent.
  config?: Record<string, unknown>
}

export const useSourceStats = () =>
  useQuery({ queryKey: ['stats', 'sources'], queryFn: () => apiGet<SourceStat[]>('/api/stats/sources') })

export const useActivity = () =>
  useQuery({
    queryKey: ['activity'],
    queryFn: () => apiGet<unknown[]>('/api/activity?limit=50'),
    refetchInterval: pollWhenVisible(15_000),
  })

export const useQueueStats = () =>
  useQuery({ queryKey: ['stats', 'queue'], queryFn: () => apiGet<{ queued: number; processing: number; dead_letter: number }>('/api/stats/queue') })

export const useDeadLetters = () =>
  useQuery({ queryKey: ['dead-letters'], queryFn: () => apiGet<{ id: string; source_type: string; error: string }[]>('/api/queue/dead-letter') })

export function useRetryDeadLetter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/queue/dead-letter/${id}/retry`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dead-letters'] })
      qc.invalidateQueries({ queryKey: ['stats', 'queue'] })
    },
  })
}

export function usePurgeDeadLetter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/queue/dead-letter/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dead-letters'] }),
  })
}
```

```tsx
// ui/src/pages/Ingestion.tsx
import { useSourceStats, useDeadLetters, useRetryDeadLetter, usePurgeDeadLetter } from '@/hooks/useIngestion'
import { DataTable, type Column } from '@/components/DataTable'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { relativeTime } from '@/lib/format'
import { ApiError } from '@/lib/api'
import { useState } from 'react'

export function Ingestion() {
  const sources = useSourceStats()
  const dl = useDeadLetters()
  const retry = useRetryDeadLetter()
  const purge = usePurgeDeadLetter()
  const [retryError, setRetryError] = useState<string | null>(null)

  if (sources.isPending) return <div data-testid="ingestion-loading"><Skeleton className="h-40" /></div>
  if (sources.isError) {
    const err = sources.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load ingestion: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }
  if (sources.data.length === 0) return <EmptyState message="No ingestion runs yet" />

  const columns: Column<{ id: string; adapter_type: string; enabled: boolean; schedule: string; last_run: string | null; items_stored: number; raw_enqueued: number; in_flight: number; health_status: string }>[] = [
    { key: 'type', header: 'Adapter', render: (r) => r.adapter_type },
    { key: 'schedule', header: 'Schedule', render: (r) => r.schedule },
    { key: 'last_run', header: 'Last run', render: (r) => relativeTime(r.last_run) },
    { key: 'items_stored', header: 'items_stored', render: (r) => r.items_stored },
    { key: 'raw_enqueued', header: 'raw_enqueued', render: (r) => r.raw_enqueued },
    { key: 'in_flight', header: 'in_flight', render: (r) => r.in_flight },
    { key: 'health', header: 'Health', render: (r) => <HealthBadge status={r.health_status} /> },
  ]

  return (
    <div className="space-y-6">
      <DataTable columns={columns} rows={sources.data} rowKey={(r) => r.id} />
      {retryError && <div role="alert" className="text-destructive text-sm">Retry failed: {retryError}</div>}
      <section>
        <h2 className="mb-2 font-semibold">Dead letters</h2>
        {(dl.data ?? []).length === 0 ? (
          <EmptyState message="No dead letters" />
        ) : (
          <ul className="space-y-2">
            {(dl.data ?? []).map((d) => (
              <li key={d.id} className="flex items-center gap-3 text-sm">
                <span className="flex-1">{d.source_type}: {d.error}</span>
                <Button
                  aria-label={`Retry ${d.id}`}
                  onClick={() => retry.mutate(d.id, { onError: (e) => setRetryError((e as ApiError).message) })}
                >
                  Retry
                </Button>
                <Button variant="destructive" aria-label={`Purge ${d.id}`} onClick={() => purge.mutate(d.id)}>
                  Purge
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Ingestion.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Ingestion page with per-source qualified counts + dead-letter retry/purge"`

---

### Task E3: Sources page + two-step add-source form
**Files:**
- Create `ui/src/hooks/useSources.ts`
- Create `ui/src/components/SourceForm.tsx`
- Create `ui/src/pages/Sources.tsx`
- Test `ui/src/pages/Sources.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Sources.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Sources } from './Sources'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const adapterTypes = [
  { adapter_type: 'github', requires_connection: false, model_json_schema: { type: 'object', properties: { repos: { type: 'array', items: { type: 'string' } } } } },
  { adapter_type: 'email', requires_connection: true, model_json_schema: { type: 'object', properties: {} } },
]

function handlers(rows: unknown[] = []) {
  server.use(
    http.get('/api/stats/sources', () => HttpResponse.json(rows)),
    http.get('/api/sources/adapter-types', () => HttpResponse.json(adapterTypes)),
    http.get('/api/connections', () => HttpResponse.json([])),
  )
}

it('loading state', () => {
  server.use(http.get('/api/stats/sources', () => new Promise(() => {})))
  renderPage(<Sources />)
  expect(screen.getByTestId('sources-loading')).toBeInTheDocument()
})

it('empty state with add CTA', async () => {
  handlers([])
  renderPage(<Sources />)
  expect(await screen.findByRole('button', { name: /add your first source/i })).toBeInTheDocument()
})

it('error state surfaces request id', async () => {
  server.use(http.get('/api/stats/sources', () =>
    HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-3' } })))
  renderPage(<Sources />)
  await waitFor(() => expect(screen.getByText(/req-3/)).toBeInTheDocument())
})

it('unauthorized state', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  handlers([])
  renderPage(<Sources />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})

it('add-source happy path: pick github, submit, success toast text', async () => {
  let posted: Record<string, unknown> | null = null
  handlers([])
  server.use(
    http.post('/api/sources', async ({ request }) => {
      posted = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({ id: 'new', ...posted })
    }),
  )
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /add your first source/i }))
  await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
  await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
  await userEvent.click(screen.getByRole('button', { name: /create source/i }))
  await waitFor(() => expect(posted).toMatchObject({ adapter_type: 'github' }))
  expect(await screen.findByText(/Source added and polling live/i)).toBeInTheDocument()
})

it('add-source failure maps 422 field error', async () => {
  handlers([])
  server.use(
    http.post('/api/sources', () =>
      HttpResponse.json({ detail: { config_errors: [{ loc: ['repos'], msg: 'must be a list' }] } }, { status: 422 })),
  )
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /add your first source/i }))
  await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
  await userEvent.type(screen.getByLabelText(/repos/i), 'x')
  await userEvent.click(screen.getByRole('button', { name: /create source/i }))
  expect(await screen.findByText(/must be a list/i)).toBeInTheDocument()
})

it('optimistic enable/disable rolls back on failure', async () => {
  handlers([{ id: 's1', adapter_type: 'github', enabled: true, schedule: '*/15 * * * *', last_run: null, items_stored: 0, raw_enqueued: 0, in_flight: 0, health_status: 'healthy' }])
  server.use(http.patch('/api/sources/s1', () => HttpResponse.json({ detail: 'fail' }, { status: 500 })))
  renderPage(<Sources />)
  const toggle = await screen.findByRole('switch', { name: /toggle s1/i })
  expect(toggle).toBeChecked()
  await userEvent.click(toggle)
  // optimistic off then rollback to on
  await waitFor(() => expect(toggle).toBeChecked())
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Sources.test.tsx`
Expected: fails — placeholder `Sources` has no content.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useSources.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api'
import type { SourceStat } from './useIngestion'

export interface AdapterType {
  adapter_type: string
  requires_connection: boolean
  model_json_schema: { type: string; properties: Record<string, unknown> }
}

export const useSourceStats = () =>
  useQuery({ queryKey: ['stats', 'sources'], queryFn: () => apiGet<SourceStat[]>('/api/stats/sources') })

export const useAdapterTypes = () =>
  useQuery({ queryKey: ['adapter-types'], queryFn: () => apiGet<AdapterType[]>('/api/sources/adapter-types') })

export const useConnections = () =>
  useQuery({ queryKey: ['connections'], queryFn: () => apiGet<{ name: string; healthy: boolean }[]>('/api/connections') })

export function useCreateSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { adapter_type: string; config: Record<string, unknown>; schedule: string; enabled: boolean; connection?: string }) =>
      apiPost<{ id: string }>('/api/sources', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
      qc.invalidateQueries({ queryKey: ['stats', 'overview'] })
    },
  })
}

export function useToggleSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPatch(`/api/sources/${id}`, { enabled }),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: ['stats', 'sources'] })
      const prev = qc.getQueryData<SourceStat[]>(['stats', 'sources'])
      qc.setQueryData<SourceStat[]>(['stats', 'sources'], (old) =>
        (old ?? []).map((s) => (s.id === id ? { ...s, enabled } : s)))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['stats', 'sources'], ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}

export function useDeleteSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}
```

```tsx
// ui/src/components/SourceForm.tsx
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { useAdapterTypes, useConnections, useCreateSource } from '@/hooks/useSources'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { toast } from 'sonner'

// zod discriminated union mirroring each provider's ProviderConfig.
const githubSchema = z.object({
  adapter_type: z.literal('github'),
  repos: z.string().min(1, 'enter at least one repo'),
})
const emailSchema = z.object({
  adapter_type: z.literal('email'),
  connection: z.string().min(1, 'select a connection'),
})
const formSchema = z.discriminatedUnion('adapter_type', [githubSchema, emailSchema])
type FormValues = z.infer<typeof formSchema>

export function SourceForm({ onDone }: { onDone: () => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const adapterTypes = useAdapterTypes()
  const connections = useConnections()
  const create = useCreateSource()
  const { register, handleSubmit, setError, formState } = useForm<FormValues>()

  if (!picked) {
    return (
      <div className="space-y-2">
        <p className="font-medium">Pick an adapter type</p>
        {(adapterTypes.data ?? []).map((t) => {
          const noConn = t.requires_connection && (connections.data ?? []).length === 0
          return (
            <Button key={t.adapter_type} disabled={noConn} onClick={() => setPicked(t.adapter_type)}>
              {t.adapter_type}
            </Button>
          )
        })}
      </div>
    )
  }

  const onSubmit = handleSubmit(async (values) => {
    const config: Record<string, unknown> = {}
    let connection: string | undefined
    if (picked === 'github') config.repos = String((values as { repos: string }).repos).split(',').map((s) => s.trim())
    if (picked === 'email') connection = (values as { connection: string }).connection
    try {
      await create.mutateAsync({ adapter_type: picked, config, schedule: '*/15 * * * *', enabled: true, connection })
      toast.success('Source added and polling live')
      onDone()
    } catch (e) {
      const err = e as ApiError
      // map field-level 422 errors to the offending fields
      try {
        const parsed = JSON.parse(err.message) as { config_errors?: { loc: string[]; msg: string }[] }
        for (const fe of parsed.config_errors ?? []) {
          setError(fe.loc[fe.loc.length - 1] as keyof FormValues, { message: fe.msg })
        }
      } catch { /* non-field error */ }
    }
  })

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <p className="text-sm text-muted-foreground">adapter_type: {picked} (immutable)</p>
      {picked === 'github' && (
        <label className="block text-sm">
          repos (comma-separated)
          <input aria-label="repos" {...register('repos')} className="mt-1 block w-full rounded border border-border bg-background p-2" />
          {formState.errors.repos && <span className="text-destructive text-xs">{formState.errors.repos.message}</span>}
          <span className="block text-xs text-muted-foreground">Uses ambient gh auth — no secret needed.</span>
        </label>
      )}
      {picked === 'email' && (
        <label className="block text-sm">
          connection
          <select aria-label="connection" {...register('connection')} className="mt-1 block w-full rounded border border-border bg-background p-2">
            {(connections.data ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          {formState.errors.connection && <span className="text-destructive text-xs">{formState.errors.connection.message}</span>}
        </label>
      )}
      <Button type="submit" disabled={create.isPending}>Create source</Button>
    </form>
  )
}
```

```tsx
// ui/src/pages/Sources.tsx
import { useState } from 'react'
import { useSourceStats, useToggleSource } from '@/hooks/useSources'
import { SourceForm } from '@/components/SourceForm'
import { DataTable, type Column } from '@/components/DataTable'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { relativeTime } from '@/lib/format'
import { ApiError } from '@/lib/api'
import type { SourceStat } from '@/hooks/useIngestion'

export function Sources() {
  const stats = useSourceStats()
  const toggle = useToggleSource()
  const [adding, setAdding] = useState(false)

  if (stats.isPending) return <div data-testid="sources-loading"><Skeleton className="h-40" /></div>
  if (stats.isError) {
    const err = stats.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load sources: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  if (adding) return <SourceForm onDone={() => setAdding(false)} />

  if (stats.data.length === 0) {
    return <EmptyState message="No sources configured" cta={<Button onClick={() => setAdding(true)}>Add your first source</Button>} />
  }

  const columns: Column<SourceStat>[] = [
    { key: 'type', header: 'Adapter', render: (r) => r.adapter_type },
    { key: 'enabled', header: 'Enabled', render: (r) => (
      <Switch
        aria-label={`Toggle ${r.id}`}
        checked={r.enabled}
        onCheckedChange={(v) => toggle.mutate({ id: r.id, enabled: v })}
      />
    ) },
    { key: 'schedule', header: 'Schedule', render: (r) => r.schedule },
    { key: 'last_run', header: 'Last run', render: (r) => relativeTime(r.last_run) },
    { key: 'items_stored', header: 'items_stored', render: (r) => r.items_stored },
    { key: 'health', header: 'Health', render: (r) => <HealthBadge status={r.health_status} /> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button onClick={() => setAdding(true)}>Add source</Button></div>
      <DataTable columns={columns} rows={stats.data} rowKey={(r) => r.id} />
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Sources.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Sources page + two-step add-source form (zod union, optimistic toggle, 422 mapping)"`

> Tasks E3b and E3c extend this page. E3c replaces `SourceForm.tsx` in full with edit-mode support and schedule controls (removing the hardcoded `schedule: '*/15 * * * *'`); E3b replaces `Sources.tsx` in full with the per-row kebab actions. Each sub-task below carries the complete final file contents — apply them as written, overwriting the E3 versions.

---

### Task E3b: Sources per-row kebab actions (edit / poll-now / enable-disable / delete)
**Files:**
- Modify `ui/src/hooks/useSources.ts` (add `usePollSource`; `useDeleteSource` gains optimistic removal + rollback)
- Modify `ui/src/pages/Sources.tsx` (replace in full — add the kebab `DropdownMenu` and the delete confirm `Dialog`)
- Test `ui/src/pages/Sources.kebab.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Sources.kebab.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Sources } from './Sources'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const adapterTypes = [
  { adapter_type: 'github', requires_connection: false, model_json_schema: { type: 'object', properties: { repos: { type: 'array', items: { type: 'string' } } } } },
]

function handlers(rows: unknown[]) {
  server.use(
    http.get('/api/stats/sources', () => HttpResponse.json(rows)),
    http.get('/api/sources/adapter-types', () => HttpResponse.json(adapterTypes)),
    http.get('/api/connections', () => HttpResponse.json([])),
  )
}

const row = {
  id: 's1', adapter_type: 'github', enabled: true, schedule: '*/15 * * * *',
  last_run: null, items_stored: 0, raw_enqueued: 0, in_flight: 0, health_status: 'healthy',
  config: { repos: ['meta/workbench'] },
}

it('poll-now calls POST /poll, toasts, and invalidates', async () => {
  let polled = false
  handlers([row])
  server.use(http.post('/api/sources/s1/poll', () => { polled = true; return HttpResponse.json({ status: 'started' }) }))
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /actions for s1/i }))
  await userEvent.click(await screen.findByRole('menuitem', { name: /poll.?now/i }))
  await waitFor(() => expect(polled).toBe(true))
  expect(await screen.findByText(/poll started/i)).toBeInTheDocument()
})

it('enable/disable from the kebab toggles via PATCH', async () => {
  let patched: Record<string, unknown> | null = null
  handlers([row])
  server.use(http.patch('/api/sources/s1', async ({ request }) => { patched = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ id: 's1' }) }))
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /actions for s1/i }))
  await userEvent.click(await screen.findByRole('menuitem', { name: /disable/i }))
  await waitFor(() => expect(patched).toMatchObject({ enabled: false }))
})

it('delete behind confirm dialog optimistically removes the row', async () => {
  let deleted = false
  handlers([row])
  server.use(http.delete('/api/sources/s1', () => { deleted = true; return new HttpResponse(null, { status: 204 }) }))
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /actions for s1/i }))
  await userEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
  await userEvent.click(await screen.findByRole('button', { name: /^delete$/i }))
  await waitFor(() => expect(deleted).toBe(true))
  await waitFor(() => expect(screen.queryByRole('button', { name: /actions for s1/i })).not.toBeInTheDocument())
})

it('delete rolls back the row when the server fails', async () => {
  handlers([row])
  server.use(http.delete('/api/sources/s1', () => HttpResponse.json({ detail: 'nope' }, { status: 500 })))
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /actions for s1/i }))
  await userEvent.click(await screen.findByRole('menuitem', { name: /delete/i }))
  await userEvent.click(await screen.findByRole('button', { name: /^delete$/i }))
  await waitFor(() => expect(screen.getByRole('button', { name: /actions for s1/i })).toBeInTheDocument())
})

it('edit opens the form in edit mode with adapter_type read-only', async () => {
  handlers([row])
  renderPage(<Sources />)
  await userEvent.click(await screen.findByRole('button', { name: /actions for s1/i }))
  await userEvent.click(await screen.findByRole('menuitem', { name: /edit/i }))
  expect(await screen.findByText(/adapter_type: github \(immutable\)/i)).toBeInTheDocument()
  // edit mode skips the adapter picker — no "Pick an adapter type" prompt
  expect(screen.queryByText(/pick an adapter type/i)).not.toBeInTheDocument()
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Sources.kebab.test.tsx`
Expected: fails — `Sources` has no kebab menu; the `actions for s1` button is absent.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useSources.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api'
import type { SourceStat } from './useIngestion'

export interface AdapterType {
  adapter_type: string
  requires_connection: boolean
  model_json_schema: { type: string; properties: Record<string, unknown> }
}

export const useSourceStats = () =>
  useQuery({ queryKey: ['stats', 'sources'], queryFn: () => apiGet<SourceStat[]>('/api/stats/sources') })

export const useAdapterTypes = () =>
  useQuery({ queryKey: ['adapter-types'], queryFn: () => apiGet<AdapterType[]>('/api/sources/adapter-types') })

export const useConnections = () =>
  useQuery({ queryKey: ['connections'], queryFn: () => apiGet<{ name: string; healthy: boolean }[]>('/api/connections') })

export function useCreateSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { adapter_type: string; config: Record<string, unknown>; schedule: string; enabled: boolean; connection?: string }) =>
      apiPost<{ id: string }>('/api/sources', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
      qc.invalidateQueries({ queryKey: ['stats', 'overview'] })
    },
  })
}

export function useEditSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: { config: Record<string, unknown>; schedule: string } }) =>
      apiPatch(`/api/sources/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats', 'sources'] })
      qc.invalidateQueries({ queryKey: ['stats', 'overview'] })
    },
  })
}

export function useToggleSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPatch(`/api/sources/${id}`, { enabled }),
    onMutate: async ({ id, enabled }) => {
      await qc.cancelQueries({ queryKey: ['stats', 'sources'] })
      const prev = qc.getQueryData<SourceStat[]>(['stats', 'sources'])
      qc.setQueryData<SourceStat[]>(['stats', 'sources'], (old) =>
        (old ?? []).map((s) => (s.id === id ? { ...s, enabled } : s)))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['stats', 'sources'], ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}

export function usePollSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/sources/${id}/poll`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}

export function useDeleteSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/sources/${id}`),
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: ['stats', 'sources'] })
      const prev = qc.getQueryData<SourceStat[]>(['stats', 'sources'])
      qc.setQueryData<SourceStat[]>(['stats', 'sources'], (old) =>
        (old ?? []).filter((s) => s.id !== id))
      return { prev }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(['stats', 'sources'], ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['stats', 'sources'] }),
  })
}
```

```tsx
// ui/src/pages/Sources.tsx
import { useState } from 'react'
import { useSourceStats, useToggleSource, usePollSource, useDeleteSource } from '@/hooks/useSources'
import { SourceForm } from '@/components/SourceForm'
import { DataTable, type Column } from '@/components/DataTable'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { relativeTime } from '@/lib/format'
import { ApiError } from '@/lib/api'
import { toast } from 'sonner'
import type { SourceStat } from '@/hooks/useIngestion'

export function Sources() {
  const stats = useSourceStats()
  const toggle = useToggleSource()
  const poll = usePollSource()
  const del = useDeleteSource()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<SourceStat | null>(null)
  const [pendingDelete, setPendingDelete] = useState<SourceStat | null>(null)

  if (stats.isPending) return <div data-testid="sources-loading"><Skeleton className="h-40" /></div>
  if (stats.isError) {
    const err = stats.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load sources: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  if (adding) return <SourceForm onDone={() => setAdding(false)} />
  if (editing) return <SourceForm source={editing} onDone={() => setEditing(null)} />

  if (stats.data.length === 0) {
    return <EmptyState message="No sources configured" cta={<Button onClick={() => setAdding(true)}>Add your first source</Button>} />
  }

  const columns: Column<SourceStat>[] = [
    { key: 'type', header: 'Adapter', render: (r) => r.adapter_type },
    { key: 'enabled', header: 'Enabled', render: (r) => (
      <Switch
        aria-label={`Toggle ${r.id}`}
        checked={r.enabled}
        onCheckedChange={(v) => toggle.mutate({ id: r.id, enabled: v })}
      />
    ) },
    { key: 'schedule', header: 'Schedule', render: (r) => r.schedule },
    { key: 'last_run', header: 'Last run', render: (r) => relativeTime(r.last_run) },
    { key: 'items_stored', header: 'items_stored', render: (r) => r.items_stored },
    { key: 'health', header: 'Health', render: (r) => <HealthBadge status={r.health_status} /> },
    { key: 'actions', header: '', render: (r) => (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" aria-label={`Actions for ${r.id}`}>⋯</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setEditing(r)}>Edit</DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => poll.mutate(r.id, { onSuccess: () => toast.success('Poll started') })}
          >
            Poll now
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => toggle.mutate({ id: r.id, enabled: !r.enabled })}>
            {r.enabled ? 'Disable' : 'Enable'}
          </DropdownMenuItem>
          <DropdownMenuItem className="text-destructive" onSelect={() => setPendingDelete(r)}>
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button onClick={() => setAdding(true)}>Add source</Button></div>
      <DataTable columns={columns} rows={stats.data} rowKey={(r) => r.id} />
      <Dialog open={pendingDelete !== null} onOpenChange={(o) => { if (!o) setPendingDelete(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete source?</DialogTitle>
            <DialogDescription>
              {pendingDelete && `This removes ${pendingDelete.adapter_type} (${pendingDelete.id}) from config.yml and stops its poll job. This cannot be undone.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPendingDelete(null)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={() => {
                const target = pendingDelete
                setPendingDelete(null)
                if (target) {
                  del.mutate(target.id, {
                    onSuccess: () => toast.success('Source deleted'),
                    onError: (e) => toast.error((e as ApiError).message),
                  })
                }
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Sources.kebab.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Sources per-row kebab (edit, poll-now, enable/disable, delete) with confirm dialog + optimistic delete rollback"`

---

### Task E3c: SourceForm edit mode + schedule controls (cron presets, advanced cron, next-run preview)
**Files:**
- Modify `ui/src/components/SourceForm.tsx` (replace in full — add `source?` edit prop, immutable `adapter_type` on edit, `PATCH` submit, and the schedule controls)
- Test `ui/src/components/SourceForm.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/components/SourceForm.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { SourceForm } from './SourceForm'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const adapterTypes = [
  { adapter_type: 'github', requires_connection: false, model_json_schema: { type: 'object', properties: { repos: { type: 'array', items: { type: 'string' } } } } },
]

function handlers() {
  server.use(
    http.get('/api/sources/adapter-types', () => HttpResponse.json(adapterTypes)),
    http.get('/api/connections', () => HttpResponse.json([])),
  )
}

const source = {
  id: 's1', adapter_type: 'github', enabled: true, schedule: '0 * * * *',
  last_run: null, items_stored: 0, raw_enqueued: 0, in_flight: 0, health_status: 'healthy',
  config: { repos: ['meta/workbench'] },
}

it('create: schedule preset Select drives the submitted cron', async () => {
  let posted: Record<string, unknown> | null = null
  handlers()
  server.use(http.post('/api/sources', async ({ request }) => { posted = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ id: 'new' }) }))
  renderPage(<SourceForm onDone={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
  await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
  // default preset is every 15 min; pick hourly instead
  await userEvent.selectOptions(screen.getByLabelText(/schedule preset/i), '0 * * * *')
  await userEvent.click(screen.getByRole('button', { name: /create source/i }))
  await waitFor(() => expect(posted).toMatchObject({ schedule: '0 * * * *' }))
})

it('create: advanced custom cron overrides the preset', async () => {
  let posted: Record<string, unknown> | null = null
  handlers()
  server.use(http.post('/api/sources', async ({ request }) => { posted = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ id: 'new' }) }))
  renderPage(<SourceForm onDone={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
  await userEvent.type(screen.getByLabelText(/repos/i), 'meta/workbench')
  await userEvent.click(screen.getByRole('button', { name: /advanced/i }))
  const custom = screen.getByLabelText(/custom cron/i)
  await userEvent.clear(custom)
  await userEvent.type(custom, '30 2 * * 1')
  await userEvent.click(screen.getByRole('button', { name: /create source/i }))
  await waitFor(() => expect(posted).toMatchObject({ schedule: '30 2 * * 1' }))
})

it('create: next-run preview renders for a valid cron and warns on invalid', async () => {
  handlers()
  renderPage(<SourceForm onDone={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: /^github$/i }))
  expect(await screen.findByText(/next run:/i)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /advanced/i }))
  const custom = screen.getByLabelText(/custom cron/i)
  await userEvent.clear(custom)
  await userEvent.type(custom, 'not a cron')
  expect(await screen.findByText(/invalid cron/i)).toBeInTheDocument()
})

it('edit mode: adapter_type read-only, prefilled config, submits PATCH', async () => {
  let patched: Record<string, unknown> | null = null
  handlers()
  server.use(http.patch('/api/sources/s1', async ({ request }) => { patched = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ id: 's1' }) }))
  renderPage(<SourceForm source={source} onDone={() => {}} />)
  // no adapter picker in edit mode
  expect(screen.queryByText(/pick an adapter type/i)).not.toBeInTheDocument()
  expect(await screen.findByText(/adapter_type: github \(immutable\)/i)).toBeInTheDocument()
  expect((screen.getByLabelText(/repos/i) as HTMLInputElement).value).toBe('meta/workbench')
  await userEvent.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(patched).toMatchObject({ schedule: '0 * * * *', config: { repos: ['meta/workbench'] } }))
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/components/SourceForm.test.tsx`
Expected: fails — current `SourceForm` has no schedule preset Select, no advanced cron field, no next-run preview, and no `source`/edit-mode prop.

- [ ] Step 3: Write minimal implementation

```tsx
// ui/src/components/SourceForm.tsx
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import parser from 'cron-parser'
import { useAdapterTypes, useConnections, useCreateSource, useEditSource } from '@/hooks/useSources'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { toast } from 'sonner'
import type { SourceStat } from '@/hooks/useIngestion'

// zod discriminated union mirroring each provider's ProviderConfig.
const githubSchema = z.object({
  adapter_type: z.literal('github'),
  repos: z.string().min(1, 'enter at least one repo'),
})
const emailSchema = z.object({
  adapter_type: z.literal('email'),
  connection: z.string().min(1, 'select a connection'),
})
const formSchema = z.discriminatedUnion('adapter_type', [githubSchema, emailSchema])
type FormValues = z.infer<typeof formSchema>

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: 'Every 15 minutes', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: 'Daily at 9am', cron: '0 9 * * *' },
]

function nextRunPreview(cron: string): string {
  try {
    const next = parser.parseExpression(cron).next().toDate()
    return `Next run: ${next.toLocaleString()}`
  } catch {
    return 'Invalid cron expression'
  }
}

interface SourceFormProps {
  onDone: () => void
  source?: SourceStat
}

export function SourceForm({ onDone, source }: SourceFormProps) {
  const editing = source !== undefined
  const adapterTypes = useAdapterTypes()
  const connections = useConnections()
  const create = useCreateSource()
  const edit = useEditSource()
  const [picked, setPicked] = useState<string | null>(editing ? source!.adapter_type : null)
  const [schedule, setSchedule] = useState<string>(editing ? source!.schedule : CRON_PRESETS[0].cron)
  const [advanced, setAdvanced] = useState(false)

  const repos0 = (source?.config as { repos?: unknown[] } | undefined)?.repos
  const initialRepos = Array.isArray(repos0) ? (repos0 as string[]).join(', ') : ''
  const { register, handleSubmit, setError, formState } = useForm<FormValues>({
    defaultValues: { repos: initialRepos } as Partial<FormValues>,
  })

  if (!picked) {
    return (
      <div className="space-y-2">
        <p className="font-medium">Pick an adapter type</p>
        {(adapterTypes.data ?? []).map((t) => {
          const noConn = t.requires_connection && (connections.data ?? []).length === 0
          return (
            <Button key={t.adapter_type} disabled={noConn} onClick={() => setPicked(t.adapter_type)}>
              {t.adapter_type}
            </Button>
          )
        })}
      </div>
    )
  }

  const onSubmit = handleSubmit(async (values) => {
    const config: Record<string, unknown> = {}
    let connection: string | undefined
    if (picked === 'github') config.repos = String((values as { repos: string }).repos).split(',').map((s) => s.trim()).filter(Boolean)
    if (picked === 'email') connection = (values as { connection: string }).connection
    try {
      if (editing) {
        await edit.mutateAsync({ id: source!.id, body: { config, schedule } })
        toast.success('Source updated')
      } else {
        await create.mutateAsync({ adapter_type: picked, config, schedule, enabled: true, connection })
        toast.success('Source added and polling live')
      }
      onDone()
    } catch (e) {
      const err = e as ApiError
      // map field-level 422 errors to the offending fields
      try {
        const parsed = JSON.parse(err.message) as { config_errors?: { loc: string[]; msg: string }[] }
        for (const fe of parsed.config_errors ?? []) {
          setError(fe.loc[fe.loc.length - 1] as keyof FormValues, { message: fe.msg })
        }
      } catch { /* non-field error */ }
    }
  })

  const pending = editing ? edit.isPending : create.isPending

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <p className="text-sm text-muted-foreground">adapter_type: {picked} (immutable)</p>
      {picked === 'github' && (
        <label className="block text-sm">
          repos (comma-separated)
          <input aria-label="repos" {...register('repos')} className="mt-1 block w-full rounded border border-border bg-background p-2" />
          {formState.errors.repos && <span className="text-destructive text-xs">{formState.errors.repos.message}</span>}
          <span className="block text-xs text-muted-foreground">Uses ambient gh auth — no secret needed.</span>
        </label>
      )}
      {picked === 'email' && (
        <label className="block text-sm">
          connection
          <select aria-label="connection" {...register('connection')} className="mt-1 block w-full rounded border border-border bg-background p-2">
            {(connections.data ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          {formState.errors.connection && <span className="text-destructive text-xs">{formState.errors.connection.message}</span>}
        </label>
      )}
      <div className="space-y-2">
        <label className="block text-sm">
          Schedule preset
          <select
            aria-label="Schedule preset"
            value={CRON_PRESETS.some((p) => p.cron === schedule) ? schedule : ''}
            disabled={advanced}
            onChange={(e) => setSchedule(e.target.value)}
            className="mt-1 block w-full rounded border border-border bg-background p-2"
          >
            {CRON_PRESETS.map((p) => <option key={p.cron} value={p.cron}>{p.label}</option>)}
            {advanced && <option value="">Custom</option>}
          </select>
        </label>
        <Button type="button" variant="ghost" size="sm" onClick={() => setAdvanced((a) => !a)}>
          {advanced ? 'Use presets' : 'Advanced'}
        </Button>
        {advanced && (
          <label className="block text-sm">
            Custom cron
            <input
              aria-label="Custom cron"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="mt-1 block w-full rounded border border-border bg-background p-2 font-mono"
            />
          </label>
        )}
        <p className="text-xs text-muted-foreground">{nextRunPreview(schedule)}</p>
      </div>
      <Button type="submit" disabled={pending}>{editing ? 'Save changes' : 'Create source'}</Button>
    </form>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/components/SourceForm.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): SourceForm edit mode (immutable adapter_type, PATCH) + cron preset/advanced controls with next-run preview"`

---

### Task E4: Messenger page (read + edit)
**Files:**
- Create `ui/src/hooks/useMessenger.ts`
- Create `ui/src/pages/Messenger.tsx`
- Test `ui/src/pages/Messenger.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Messenger.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Messenger } from './Messenger'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

it('loading state', () => {
  server.use(http.get('/api/messenger', () => new Promise(() => {})))
  renderPage(<Messenger />)
  expect(screen.getByTestId('messenger-loading')).toBeInTheDocument()
})

it('degraded state when not configured shows pending count', async () => {
  server.use(
    http.get('/api/messenger', () => HttpResponse.json({ configured: false, type: null, class: null, config: {} })),
    http.get('/api/triage/pending', () => HttpResponse.json([{ id: 'c1' }, { id: 'c2' }])),
  )
  renderPage(<Messenger />)
  expect(await screen.findByText(/no messenger/i)).toBeInTheDocument()
  expect(screen.getByText(/2/)).toBeInTheDocument()
})

it('happy path shows allowlisted config and reachability', async () => {
  server.use(http.get('/api/messenger', () =>
    HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: { space_id: 'spaces/AAA', timeout_seconds: 5 }, reachable: true, checked_at: '2026-06-05T00:00:00Z' })))
  renderPage(<Messenger />)
  expect(await screen.findByText('spaces/AAA')).toBeInTheDocument()
  expect(screen.queryByText(/service_account_key_path/i)).not.toBeInTheDocument()
})

it('error state surfaces request id', async () => {
  server.use(http.get('/api/messenger', () =>
    HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-2' } })))
  renderPage(<Messenger />)
  await waitFor(() => expect(screen.getByText(/req-2/)).toBeInTheDocument())
})

it('unauthorized state', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  server.use(http.get('/api/messenger', () => HttpResponse.json({ configured: true, config: {} })))
  renderPage(<Messenger />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})

it('edit happy path submits PATCH', async () => {
  let patched: Record<string, unknown> | null = null
  server.use(
    http.get('/api/messenger', () => HttpResponse.json({ configured: true, type: 'gchat', class: 'GChatMessenger', config: { space_id: 'spaces/AAA', timeout_seconds: 5 } })),
    http.patch('/api/messenger', async ({ request }) => { patched = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ status: 'updated' }) }),
  )
  renderPage(<Messenger />)
  const input = await screen.findByLabelText(/space_id/i)
  await userEvent.clear(input)
  await userEvent.type(input, 'spaces/BBB')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))
  await waitFor(() => expect(patched).toMatchObject({ space_id: 'spaces/BBB' }))
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Messenger.test.tsx`
Expected: fails — placeholder page.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useMessenger.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPatch } from '@/lib/api'

export interface MessengerInfo {
  configured: boolean
  type: string | null
  class: string | null
  config: { space_id?: string; timeout_seconds?: number }
  reachable?: boolean
  checked_at?: string
}

export const useMessenger = () =>
  useQuery({ queryKey: ['messenger'], queryFn: () => apiGet<MessengerInfo>('/api/messenger?check=true') })

export const usePendingCount = (enabled: boolean) =>
  useQuery({
    queryKey: ['triage', 'pending'],
    queryFn: () => apiGet<unknown[]>('/api/triage/pending'),
    enabled,
  })

export function useUpdateMessenger() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { space_id?: string; timeout_seconds?: number }) => apiPatch('/api/messenger', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['messenger'] }),
  })
}
```

```tsx
// ui/src/pages/Messenger.tsx
import { useState } from 'react'
import { useMessenger, usePendingCount, useUpdateMessenger } from '@/hooks/useMessenger'
import { HealthBadge } from '@/components/HealthBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'

export function Messenger() {
  const m = useMessenger()
  const pending = usePendingCount(m.data?.configured === false)
  const update = useUpdateMessenger()
  const [spaceId, setSpaceId] = useState('')

  if (m.isPending) return <div data-testid="messenger-loading"><Skeleton className="h-40" /></div>
  if (m.isError) {
    const err = m.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load messenger: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  if (!m.data.configured) {
    return (
      <div className="rounded border border-border p-4">
        <p className="font-medium">No messenger configured</p>
        <p className="text-sm text-muted-foreground">
          Triage cards are queued but unsent. Pending: {(pending.data ?? []).length}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="font-medium">{m.data.class}</span>
        {m.data.reachable !== undefined && <HealthBadge status={m.data.reachable ? 'healthy' : 'erroring'} />}
      </div>
      <p>space_id: {m.data.config.space_id}</p>
      <p>timeout_seconds: {m.data.config.timeout_seconds}</p>
      <form
        className="space-y-2"
        onSubmit={(e) => { e.preventDefault(); update.mutate({ space_id: spaceId || m.data.config.space_id }) }}
      >
        <label className="block text-sm">
          space_id
          <input
            aria-label="space_id"
            defaultValue={m.data.config.space_id}
            onChange={(e) => setSpaceId(e.target.value)}
            className="mt-1 block w-full rounded border border-border bg-background p-2"
          />
        </label>
        <Button type="submit" disabled={update.isPending}>Save</Button>
      </form>
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Messenger.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Messenger page (read allowlisted config + reachability + edit, degraded state)"`

---

### Task E5: Knowledge page + Fact Curation
**Files:**
- Create `ui/src/hooks/useFacts.ts`
- Create `ui/src/components/FactRow.tsx`
- Create `ui/src/pages/Knowledge.tsx`
- Test `ui/src/pages/Knowledge.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Knowledge.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Knowledge } from './Knowledge'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

it('loading state', () => {
  server.use(http.get('/api/memory/facts', () => new Promise(() => {})))
  renderPage(<Knowledge />)
  expect(screen.getByTestId('knowledge-loading')).toBeInTheDocument()
})

it('degraded: noop memory', async () => {
  server.use(http.get('/api/memory/facts', () => HttpResponse.json({ available: false, memory_type: 'noop', facts: [] })))
  renderPage(<Knowledge />)
  expect(await screen.findByText(/Memory layer not enabled/i)).toBeInTheDocument()
})

it('degraded: configured but unreachable shows request id', async () => {
  server.use(http.get('/api/memory/facts', () =>
    HttpResponse.json({ available: false, memory_type: 'zep', facts: [] }, { headers: { 'X-Request-ID': 'req-mem' } })))
  renderPage(<Knowledge />)
  expect(await screen.findByText(/Memory service unreachable/i)).toBeInTheDocument()
})

it('empty: configured no facts', async () => {
  server.use(http.get('/api/memory/facts', () => HttpResponse.json({ available: true, memory_type: 'zep', facts: [] })))
  renderPage(<Knowledge />)
  expect(await screen.findByText(/No preference facts learned yet/i)).toBeInTheDocument()
})

it('error state', async () => {
  server.use(http.get('/api/memory/facts', () =>
    HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-5' } })))
  renderPage(<Knowledge />)
  await waitFor(() => expect(screen.getByText(/req-5/)).toBeInTheDocument())
})

it('unauthorized', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  server.use(http.get('/api/memory/facts', () => HttpResponse.json({ available: true, memory_type: 'zep', facts: [] })))
  renderPage(<Knowledge />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})

it('delete fact happy path', async () => {
  let deleted = false
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json({ available: true, memory_type: 'zep', facts: [{ id: 'f1', content: 'prioritizes blocked PRs', source: 'interaction', timestamp: '2026-06-01T00:00:00Z' }] })),
    http.delete('/api/memory/facts/f1', () => { deleted = true; return HttpResponse.json({ status: 'deleted' }) }),
  )
  renderPage(<Knowledge />)
  await userEvent.click(await screen.findByRole('button', { name: /delete f1/i }))
  await userEvent.click(await screen.findByRole('button', { name: /confirm/i }))
  await waitFor(() => expect(deleted).toBe(true))
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Knowledge.test.tsx`
Expected: fails — placeholder page.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useFacts.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPatch, apiDelete } from '@/lib/api'

export interface Fact { id: string; content: string; source: string; timestamp: string | null }
export interface FactsEnvelope { available: boolean; memory_type: string; facts: Fact[] }

export const useFacts = () =>
  useQuery({ queryKey: ['facts'], queryFn: () => apiGet<FactsEnvelope>('/api/memory/facts') })

export function useDeleteFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/memory/facts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['facts'] }),
  })
}

export function useUpdateFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) => apiPatch(`/api/memory/facts/${id}`, { content }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['facts'] }),
  })
}
```

```tsx
// ui/src/components/FactRow.tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { useDeleteFact, useUpdateFact, type Fact } from '@/hooks/useFacts'

export function FactRow({ fact }: { fact: Fact }) {
  const del = useDeleteFact()
  const upd = useUpdateFact()
  const [editValue, setEditValue] = useState(fact.content)

  return (
    <li className="flex items-center gap-3 border-b border-border py-2 text-sm">
      <span className="flex-1">{fact.content}</span>
      <span className="text-xs text-muted-foreground">{fact.source}</span>
      <Dialog>
        <DialogTrigger asChild><Button variant="outline" aria-label={`Edit ${fact.id}`}>Edit</Button></DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit fact</DialogTitle></DialogHeader>
          <input value={editValue} onChange={(e) => setEditValue(e.target.value)} className="w-full rounded border border-border bg-background p-2" />
          <DialogFooter><Button onClick={() => upd.mutate({ id: fact.id, content: editValue })}>Save</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog>
        <DialogTrigger asChild><Button variant="destructive" aria-label={`Delete ${fact.id}`}>Delete</Button></DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete this fact?</DialogTitle></DialogHeader>
          <DialogFooter><Button variant="destructive" onClick={() => del.mutate(fact.id)}>Confirm</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  )
}
```

```tsx
// ui/src/pages/Knowledge.tsx
import { useFacts } from '@/hooks/useFacts'
import { FactRow } from '@/components/FactRow'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

export function Knowledge() {
  const facts = useFacts()

  if (facts.isPending) return <div data-testid="knowledge-loading"><Skeleton className="h-40" /></div>
  if (facts.isError) {
    const err = facts.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load facts: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const env = facts.data
  if (!env.available) {
    if (env.memory_type === 'noop') {
      return <div className="rounded border border-border p-4">Memory layer not enabled</div>
    }
    return <div className="rounded border border-border p-4">Memory service unreachable</div>
  }
  if (env.facts.length === 0) return <EmptyState message="No preference facts learned yet" />

  return (
    <ul>
      {env.facts.map((f) => <FactRow key={f.id} fact={f} />)}
    </ul>
  )
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Knowledge.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Knowledge page + Fact Curation (edit/delete dialogs, three degraded states)"`

---

### Task E6: Triage page (numbered + free-text + confirm)
**Files:**
- Create `ui/src/hooks/useTriage.ts`
- Create `ui/src/pages/Triage.tsx`
- Test `ui/src/pages/Triage.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Triage.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Triage } from './Triage'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const card = {
  id: 'c1', card_content: { summary: 'Review auth PR' },
  options: [{ label: 'Add todo', action: 'add_todo' }, { label: 'Skip', action: 'skip' }],
}

it('loading state', () => {
  server.use(http.get('/api/triage/pending', () => new Promise(() => {})))
  renderPage(<Triage />)
  expect(screen.getByTestId('triage-loading')).toBeInTheDocument()
})

it('empty state inbox zero', async () => {
  server.use(http.get('/api/triage/pending', () => HttpResponse.json([])))
  renderPage(<Triage />)
  expect(await screen.findByText(/Inbox zero/i)).toBeInTheDocument()
})

it('error state', async () => {
  server.use(http.get('/api/triage/pending', () =>
    HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-6' } })))
  renderPage(<Triage />)
  await waitFor(() => expect(screen.getByText(/req-6/)).toBeInTheDocument())
})

it('unauthorized', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  server.use(http.get('/api/triage/pending', () => HttpResponse.json([card])))
  renderPage(<Triage />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})

it('numbered respond happy path', async () => {
  let posted: Record<string, unknown> | null = null
  server.use(
    http.get('/api/triage/pending', () => HttpResponse.json([card])),
    http.post('/api/triage/respond', async ({ request }) => { posted = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ status: 'recorded', action: 'add_todo' }) }),
  )
  renderPage(<Triage />)
  await userEvent.click(await screen.findByRole('button', { name: /1\. add todo/i }))
  await waitFor(() => expect(posted).toMatchObject({ card_id: 'c1', choice: 1 }))
})

it('destructive free-text opens confirm dialog and confirms', async () => {
  let confirmed: Record<string, unknown> | null = null
  server.use(
    http.get('/api/triage/pending', () => HttpResponse.json([card])),
    http.post('/api/triage/respond', () => HttpResponse.json({ status: 'awaiting_confirmation', explanation: 'will skip', card_id: 'c1' })),
    http.post('/api/triage/confirm', async ({ request }) => { confirmed = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ status: 'responded' }) }),
  )
  renderPage(<Triage />)
  await userEvent.type(await screen.findByLabelText(/free.?text/i), 'drop this')
  await userEvent.click(screen.getByRole('button', { name: /send/i }))
  expect(await screen.findByText(/will skip/i)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
  await waitFor(() => expect(confirmed).toMatchObject({ card_id: 'c1', confirm: true }))
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Triage.test.tsx`
Expected: fails — placeholder page.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useTriage.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api'
import { pollWhenVisible } from '@/lib/query-client'

export interface TriageOption { label: string; action: string }
export interface TriageCard { id: string; card_content: { summary?: string }; options: TriageOption[] }

export const useTriagePending = () =>
  useQuery({
    queryKey: ['triage', 'pending'],
    queryFn: () => apiGet<TriageCard[]>('/api/triage/pending'),
    refetchInterval: pollWhenVisible(15_000),
  })

export function useRespond() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { card_id: string; choice?: number; raw_text?: string }) =>
      apiPost<{ status: string; explanation?: string }>('/api/triage/respond', body),
    onSuccess: (data) => {
      if (data.status !== 'awaiting_confirmation') qc.invalidateQueries({ queryKey: ['triage', 'pending'] })
    },
  })
}

export function useConfirm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { card_id: string; confirm: boolean }) => apiPost('/api/triage/confirm', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['triage', 'pending'] }),
  })
}
```

```tsx
// ui/src/pages/Triage.tsx
import { useState } from 'react'
import { useTriagePending, useRespond, useConfirm, type TriageCard } from '@/hooks/useTriage'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'

function Card({ card }: { card: TriageCard }) {
  const respond = useRespond()
  const confirm = useConfirm()
  const [text, setText] = useState('')
  const [pending, setPending] = useState<{ explanation: string } | null>(null)

  const sendFreeText = async () => {
    const res = await respond.mutateAsync({ card_id: card.id, raw_text: text })
    if (res.status === 'awaiting_confirmation') setPending({ explanation: res.explanation ?? '' })
  }

  return (
    <div className="rounded border border-border p-4 space-y-3">
      <p className="font-medium">{card.card_content.summary}</p>
      <div className="flex flex-wrap gap-2">
        {card.options.map((o, i) => (
          <Button key={o.action} onClick={() => respond.mutate({ card_id: card.id, choice: i + 1 })}>
            {i + 1}. {o.label}
          </Button>
        ))}
      </div>
      <div className="flex gap-2">
        <input aria-label="free-text response" value={text} onChange={(e) => setText(e.target.value)}
          className="flex-1 rounded border border-border bg-background p-2" />
        <Button onClick={sendFreeText} disabled={!text}>Send</Button>
      </div>
      <Dialog open={pending !== null} onOpenChange={(o) => !o && setPending(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Confirm action</DialogTitle></DialogHeader>
          <p>{pending?.explanation}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => { confirm.mutate({ card_id: card.id, confirm: false }); setPending(null) }}>Cancel</Button>
            <Button onClick={() => { confirm.mutate({ card_id: card.id, confirm: true }); setPending(null) }}>Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function Triage() {
  const pending = useTriagePending()
  if (pending.isPending) return <div data-testid="triage-loading"><Skeleton className="h-40" /></div>
  if (pending.isError) {
    const err = pending.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load triage: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }
  if (pending.data.length === 0) return <EmptyState message="Inbox zero — no cards awaiting triage" />
  return <div className="space-y-4">{pending.data.map((c) => <Card key={c.id} card={c} />)}</div>
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Triage.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): Triage page (numbered + free-text respond + web confirmation dialog)"`

---

### Task E7: Migrate Action Items to TanStack Query + shared DataTable
**Files:**
- Modify `ui/src/lib/api.ts` (keep existing action fns OR re-export from new client)
- Create `ui/src/hooks/useActions.ts`
- Create `ui/src/pages/ActionItems.tsx`
- Test `ui/src/pages/ActionItems.test.tsx`

> The existing `ui/src/components/ActionList.tsx` and `ui/src/api.ts` action functions are migrated: action mutations move onto TanStack Query and the shared `DataTable`. Preserve the `/api/actions` contract.

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/ActionItems.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { ActionItems } from './ActionItems'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

const actionsResp = {
  categories: { Code: [{ id: 'a1', summary: 'Fix bug', priority: 'P1', parent_item: null, action_source: 'triage_response', action_category: 'code', created_at: '2026-06-01T00:00:00Z' }] },
  total: 1,
}

it('loading state', () => {
  server.use(http.get('/api/actions', () => new Promise(() => {})))
  renderPage(<ActionItems />)
  expect(screen.getByTestId('actions-loading')).toBeInTheDocument()
})

it('happy path lists actions', async () => {
  server.use(http.get('/api/actions', () => HttpResponse.json(actionsResp)))
  renderPage(<ActionItems />)
  expect(await screen.findByText('Fix bug')).toBeInTheDocument()
})

it('empty state', async () => {
  server.use(http.get('/api/actions', () => HttpResponse.json({ categories: {}, total: 0 })))
  renderPage(<ActionItems />)
  expect(await screen.findByText(/No action items/i)).toBeInTheDocument()
})

it('error + unauthorized', async () => {
  server.use(http.get('/api/actions', () => HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-a' } })))
  renderPage(<ActionItems />)
  await waitFor(() => expect(screen.getByText(/req-a/)).toBeInTheDocument())
})

it('mark done happy path', async () => {
  let done = false
  server.use(
    http.get('/api/actions', () => HttpResponse.json(actionsResp)),
    http.post('/api/actions/a1/done', () => { done = true; return HttpResponse.json({ status: 'done' }) }),
  )
  renderPage(<ActionItems />)
  await userEvent.click(await screen.findByRole('button', { name: /mark a1 done/i }))
  await waitFor(() => expect(done).toBe(true))
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/ActionItems.test.tsx`
Expected: fails — placeholder page.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useActions.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api'

export interface Action {
  id: string; summary: string; priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string; action_category: string | null; created_at: string
}
export interface ActionsResponse { categories: Record<string, Action[]>; total: number }

export const useActions = () =>
  useQuery({ queryKey: ['actions'], queryFn: () => apiGet<ActionsResponse>('/api/actions') })

export function useMarkDone() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/actions/${id}/done`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['actions'] }),
  })
}

export function useChangePriority() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, priority }: { id: string; priority: string }) => apiPost(`/api/actions/${id}/priority`, { priority }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['actions'] }),
  })
}

export function useSnooze() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, hours }: { id: string; hours: number }) => apiPost(`/api/actions/${id}/snooze`, { hours }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['actions'] }),
  })
}
```

```tsx
// ui/src/pages/ActionItems.tsx
import { useActions, useMarkDone, type Action } from '@/hooks/useActions'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'

export function ActionItems() {
  const actions = useActions()
  const markDone = useMarkDone()

  if (actions.isPending) return <div data-testid="actions-loading"><Skeleton className="h-40" /></div>
  if (actions.isError) {
    const err = actions.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load action items: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const rows = Object.values(actions.data.categories).flat()
  if (rows.length === 0) return <EmptyState message="No action items" />

  const columns: Column<Action>[] = [
    { key: 'summary', header: 'Summary', render: (r) => r.summary },
    { key: 'priority', header: 'Priority', render: (r) => r.priority },
    { key: 'category', header: 'Category', render: (r) => r.action_category ?? '—' },
    { key: 'done', header: '', render: (r) => (
      <Button aria-label={`Mark ${r.id} done`} onClick={() => markDone.mutate(r.id)}>Done</Button>
    ) },
  ]
  return <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
}
```

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/ActionItems.test.tsx`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "feat(ui): migrate Action Items to TanStack Query + shared DataTable"`

---

### Task E8: Settings page (read-only system info)
**Files:**
- Create `ui/src/hooks/useSettings.ts`
- Create `ui/src/pages/Settings.tsx`
- Test `ui/src/pages/Settings.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/pages/Settings.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { Settings } from './Settings'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

it('loading state', () => {
  server.use(http.get('/health', () => new Promise(() => {})))
  renderPage(<Settings />)
  expect(screen.getByTestId('settings-loading')).toBeInTheDocument()
})

it('happy path shows versions and redacted config', async () => {
  server.use(
    http.get('/health', () => HttpResponse.json({ status: 'healthy', version: '0.1.0', components: { storage: { status: 'healthy' }, connections: {} } })),
    http.get('/api/debug/config', () => HttpResponse.json({ config: { version: '0.4.0', pipeline: { include_threshold: 70 }, server: { api_token: '[REDACTED]' } } })),
  )
  renderPage(<Settings />)
  expect(await screen.findByText(/0\.1\.0/)).toBeInTheDocument()
  expect(screen.getByText(/include_threshold/)).toBeInTheDocument()
  expect(screen.queryByText(/dev-token/)).not.toBeInTheDocument()
})

it('degraded state on 503', async () => {
  server.use(
    http.get('/health', () => HttpResponse.json({ status: 'unhealthy', version: '0.1.0', components: { storage: { status: 'unhealthy' }, connections: {} } }, { status: 503 })),
    http.get('/api/debug/config', () => HttpResponse.json({ config: {} })),
  )
  renderPage(<Settings />)
  expect(await screen.findByText(/storage down/i)).toBeInTheDocument()
})

it('error state on config failure', async () => {
  server.use(
    http.get('/health', () => HttpResponse.json({ status: 'healthy', version: '0.1.0', components: { storage: { status: 'healthy' }, connections: {} } })),
    http.get('/api/debug/config', () => HttpResponse.json({ detail: 'x' }, { status: 500, headers: { 'X-Request-ID': 'req-8' } })),
  )
  renderPage(<Settings />)
  await waitFor(() => expect(screen.getByText(/req-8/)).toBeInTheDocument())
})

it('unauthorized', async () => {
  server.use(http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })))
  server.use(http.get('/health', () => HttpResponse.json({ status: 'healthy', version: '0.1.0', components: { storage: { status: 'healthy' }, connections: {} } })))
  server.use(http.get('/api/debug/config', () => HttpResponse.json({ config: {} })))
  renderPage(<Settings />)
  await waitFor(() => expect(screen.getByText(/token unavailable/i)).toBeInTheDocument())
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/pages/Settings.test.tsx`
Expected: fails — placeholder page.

- [ ] Step 3: Write minimal implementation

```ts
// ui/src/hooks/useSettings.ts
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'

export interface Health {
  status: string; version: string
  components: { storage: { status: string }; connections: Record<string, { status: string }> }
}

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: () => apiGet<Health>('/health'), retry: false })

export const useDebugConfig = () =>
  useQuery({ queryKey: ['debug-config'], queryFn: () => apiGet<{ config: Record<string, unknown> }>('/api/debug/config') })
```

```tsx
// ui/src/pages/Settings.tsx
import { useHealth, useDebugConfig } from '@/hooks/useSettings'
import { HealthBadge } from '@/components/HealthBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

const SECTIONS = ['pipeline', 'scheduler', 'retention', 'alerting']

export function Settings() {
  const health = useHealth()
  const cfg = useDebugConfig()

  if (health.isPending) return <div data-testid="settings-loading"><Skeleton className="h-40" /></div>

  if (cfg.isError) {
    const err = cfg.error as ApiError
    if (err.status === 401) return <div role="alert" className="p-6">token unavailable; check tunnel/binding</div>
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load config: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const degraded = health.data?.status === 'unhealthy'
  const config = (cfg.data?.config ?? {}) as Record<string, Record<string, unknown>>

  return (
    <div className="space-y-4">
      {degraded && <div role="alert" className="rounded border border-destructive p-3 text-sm">storage down — showing last-known statuses</div>}
      <div className="flex items-center gap-3">
        <span>App version: {health.data?.version}</span>
        <span>Config version: {String(config.version ?? '—')}</span>
        <HealthBadge status={health.data?.components.storage.status === 'healthy' ? 'healthy' : 'erroring'} />
      </div>
      {SECTIONS.map((s) => (
        <section key={s} className="rounded border border-border p-3">
          <h2 className="mb-2 font-semibold">{s}</h2>
          <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(config[s] ?? {}, null, 2)}</pre>
        </section>
      ))}
    </div>
  )
}
```

> Note: the `<pre>{JSON.stringify(...)}</pre>` renders config text as React text nodes (no `dangerouslySetInnerHTML`), consistent with the `react/no-danger` ban.

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/pages/Settings.test.tsx && npm run build`
Expected: PASS and build succeeds.

- [ ] Step 5: Commit
`git commit -am "feat(ui): Settings page (versions, component health, read-only redacted config sections)"`

---

## PHASE F — Hardening

### Task F1: Accessibility pass (keyboard nav, focus trap/return, aria-labels, contrast, focus rings)
**Files:**
- Modify `ui/src/components/AppSidebar.tsx`, `ui/src/components/DataTable.tsx`, priority badge styles in `ui/src/index.css`
- Add `eslint-plugin-jsx-a11y` + `react/no-danger` to `ui/.eslintrc`/`eslint.config.js`
- Test `ui/src/a11y.test.tsx`

- [ ] Step 1: Write the failing test

```tsx
// ui/src/a11y.test.tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { renderPage } from '@/test/render'
import { _resetToken } from '@/lib/api'
import { AppSidebar } from '@/components/AppSidebar'
import { FactRow } from '@/components/FactRow'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

it('sidebar nav is keyboard reachable and labeled', async () => {
  renderPage(<AppSidebar />)
  expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument()
  await userEvent.tab()
  // first nav link receives focus
  expect(screen.getByRole('link', { name: 'Overview' })).toHaveFocus()
})

it('icon/destructive buttons carry aria-labels', () => {
  renderPage(<FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />)
  expect(screen.getByRole('button', { name: /edit f9/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /delete f9/i })).toBeInTheDocument()
})

it('dialog returns focus to trigger on close', async () => {
  renderPage(<FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />)
  const trigger = screen.getByRole('button', { name: /delete f9/i })
  await userEvent.click(trigger)
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  // shadcn Dialog (Radix) returns focus to the trigger on close
  expect(trigger).toHaveFocus()
})
```

- [ ] Step 2: Run test to verify it fails
Run: `cd ui && npx vitest run src/a11y.test.tsx`
Expected: the focus-on-tab assertion fails if the sidebar links are not natively focusable in order; the dialog focus-return fails if a non-Radix dialog is used. (If all pass with the D2/E5 components, add the P0–P3 contrast assertion below and make it fail first.)

- [ ] Step 3: Write minimal implementation

Confirm sidebar uses `NavLink` (focusable `<a>`) — already done in D2. Add a visible focus ring utility to all interactive elements via `index.css`:

```css
a, button, [role="switch"], select, input {
  outline-offset: 2px;
}
a:focus-visible, button:focus-visible, [role="switch"]:focus-visible,
select:focus-visible, input:focus-visible {
  outline: 2px solid var(--ring);
}
```

Add dark-contrast-safe P0–P3 priority badge tokens to `index.css`:

```css
.prio-P0 { background: oklch(0.55 0.22 25); color: white; }
.prio-P1 { background: oklch(0.62 0.17 50); color: black; }
.prio-P2 { background: oklch(0.70 0.13 250); color: black; }
.prio-P3 { background: oklch(0.55 0 0); color: white; }
```

Add ESLint a11y + no-danger rule. In `ui/eslint.config.js` add `eslint-plugin-jsx-a11y` recommended config and:

```js
rules: {
  'react/no-danger': 'error',
  'jsx-a11y/control-has-associated-label': 'warn',
}
```

Add `eslint-plugin-jsx-a11y` and `eslint-plugin-react` to `ui/package.json` devDependencies.

The shadcn `Dialog` (Radix) already provides focus trap + focus return; the `FactRow` Delete/Edit triggers and `Triage` confirm dialog use it. No code change needed beyond confirming Radix is the dialog primitive (it is, from `npx shadcn add dialog`).

- [ ] Step 4: Run test to verify it passes
Run: `cd ui && npx vitest run src/a11y.test.tsx && npx eslint src --max-warnings 50`
Expected: PASS; eslint reports no `react/no-danger` errors.

- [ ] Step 5: Commit
`git commit -am "feat(ui): a11y pass — focus rings, aria-labels, dialog focus return, P0-P3 contrast, no-danger lint"`

---

### Task F2: Docs — README UI section + build-before-package note
**Files:**
- Modify `README.md` (UI section)
- No automated test (docs)

- [ ] Step 1: Write the failing test
Docs task — the "test" is a content check via grep.
Run: `grep -c "Management Dashboard" README.md`
Expected (before): `0`

- [ ] Step 2: Run to verify it fails
Run: `grep -q "npm run build" README.md && echo FOUND || echo MISSING`
Expected: `MISSING`

- [ ] Step 3: Write minimal implementation
Add a "Management Dashboard (Web UI)" section to `README.md` documenting:
- The SPA at `/ui`, served from the static mount, reached over the SSH tunnel.
- Build before packaging: `cd ui && npm install && npm run build` produces `ui/dist`, which `main.py` mounts at `/ui` only if present.
- `npm run gen:api` regenerates `ui/src/lib/api-types.ts` from `/openapi.json` (server must be running on `127.0.0.1:8421`).
- The Token-Vending Endpoint and the SSH-tunnel security boundary (loopback bind).
- Dev: `cd ui && npm run dev` with the Vite `/api` proxy to `localhost:8421`.

- [ ] Step 4: Run to verify it passes
Run: `grep -q "Management Dashboard" README.md && grep -q "npm run build" README.md && echo OK`
Expected: `OK`

- [ ] Step 5: Commit
`git commit -am "docs: README Management Dashboard section + build-before-package + gen:api notes"`

---

### Task F3: Loopback bind recommendation + SSH-tunnel boundary doc
**Files:**
- Modify `src/workbench/main.py` (`cli_main` host)
- Modify `README.md` / `docs/` (security perimeter note)
- Test `tests/test_loopback_bind.py`

- [ ] Step 1: Write the failing test

```python
# tests/test_loopback_bind.py
import inspect
from workbench import main


def test_cli_main_binds_loopback_by_default():
    src = inspect.getsource(main.cli_main)
    # default host must be loopback; "::" (all interfaces) must not be the hardcoded default
    assert "127.0.0.1" in src or "::1" in src
    assert 'host="::"' not in src
```

- [ ] Step 2: Run test to verify it fails
Run: `python -m pytest tests/test_loopback_bind.py -v`
Expected: fails — `cli_main` currently hardcodes `host="::"`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/main.py`, change `cli_main` to bind loopback by default (overridable via env for advanced setups):

```python
def cli_main():
    import os
    import uvicorn
    config = get_config()
    host = os.environ.get("WORKBENCH_HOST", "127.0.0.1")
    uvicorn.run("workbench.main:app", host=host, port=config.server.port,
                reload=config.server.debug)
```

Add a "Security perimeter" note to `README.md`/`docs/`: the server binds `127.0.0.1` by default; the Token-Vending Endpoint is auth-exempt and only safe under loopback/SSH-tunnel isolation; reaching the UI from another host is done by forwarding the port over SSH (`ssh -L 8421:127.0.0.1:8421 devgpu`), never by binding `0.0.0.0`/`::`.

- [ ] Step 4: Run test to verify it passes
Run: `python -m pytest tests/test_loopback_bind.py -v`
Expected: PASS

- [ ] Step 5: Commit
`git commit -am "fix(security): default loopback bind in cli_main + document SSH-tunnel perimeter"`

---

## Final verification (run after all phases)

- [ ] Backend full suite: `alembic upgrade head && python -m pytest tests/ -v --tb=short` — all green.
- [ ] Frontend full suite: `cd ui && npm run test` — all page + api + a11y tests green.
- [ ] Build: `cd ui && npm run build` — `dist/` produced; `tailwind.config.js`/`postcss.config.js`/`autoprefixer` absent.
- [ ] Types: `cd ui && npm run gen:api` — `src/lib/api-types.ts` regenerates cleanly against `/openapi.json`.
- [ ] Manual: navigate to `/ui` over the SSH tunnel; Overview renders without a manual token paste; add a `github` source and confirm it polls without restart (success toast); confirm `config.yml` retains `${oc.env:...}` and comments.
