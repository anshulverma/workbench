# Cross-Entity Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Each task is a self-contained red-green-commit TDD cycle. Do the steps in order, never skip the "run the test and watch it fail" step, repeat all code verbatim (no "same as Task N"), and commit at the end of every task. Do not batch tasks.

## Goal

Extend the shipped item-lineage feature (every `Item` has a stable materialized `path` like `#123`, `#123.1.2`) outward to every OTHER entity the system creates — LLM calls, interactions, plans, triage cards, and a new durable message record — so each links back to the EXACT item path(s) it consumed, at true depth. The mechanism is a single generic bidirectional join table `entity_item_links`. A `GET /api/items/{path}/related` endpoint and an `ItemPage` "What touched this" section expose reverse lineage. Three latent lineage bugs found while grilling are fixed along the way (empty `item_paths` on extraction + simple-site scoring; unstamped `generate_card`; mis-stamped batched-scoring root link).

## Architecture

Two recording paths feed one table:

- **Call-time path** — taken when the consumed item paths are known at the call site (extraction, triage `generate_card`, free-text interpret, re-triage, message sends). The caller stamps `LLMCallContext.item_paths` (or passes paths directly to `EntityLinkStore.record`), and for LLM calls the writer derives both `LlmCallRecord.items` and the `entity_item_links` rows inside `save_many` AFTER the `llm_calls` id is assigned.
- **Post-persist path** — taken when consumed items are born AFTER the call returns (batched/non-batched relevance scoring, batched urgency). The caller stamps a client-generated `correlation_id`; the call persists with that `correlation_id` column, and once the children/roots are allocated the creation site calls `record_by_correlation` to write the link rows (entity_id left NULL, resolved by joining `llm_calls.correlation_id` at query time).

`entity_item_links(id, entity_type TEXT, entity_id BIGINT NULL, item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE, item_path TEXT NOT NULL, correlation_id TEXT NULL, created_at)` is the single source of truth for cross-entity edges. The item side uses `ON DELETE CASCADE`; the entity side has no DB FK, so retention pruners call `unlink_entity`. The three existing depth-0 FK entities (`TriageCard`/`EnrichmentTrace`/`FeedbackCorrection`) keep their columns and are UNIONed into the reverse-lookup endpoint. A new durable `messages` table makes every send/receive a linkable record.

See ADR 0063 (generic join table) and ADR 0064 (correlation-id linkage).

## Tech Stack

- Backend: Python 3.12, FastAPI, asyncpg, Pydantic v2, Alembic, pytest + pytest-asyncio.
- Storage: PostgreSQL (running locally for tests; `conftest` TRUNCATEs between tests).
- Frontend: React 18 + TypeScript, @tanstack/react-query, vitest + @testing-library/react + msw.

## Test commands

- Backend single: `$HOME/.venv/workbench/bin/python -m pytest tests/<file>::<test> -v --tb=short`
- Backend full: `$HOME/.venv/workbench/bin/python -m pytest tests/ -q`
- Apply schema (run after writing migration 015): `$HOME/.venv/workbench/bin/python -m alembic upgrade head`
- UI single: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run src/<path>` (do NOT use `npm exec`)
- UI build: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run build`

Postgres must be running and schema must be at head (`alembic upgrade head`) before backend store tests.

## File Structure

| File | New/Modify | Purpose |
|------|-----------|---------|
| `src/workbench/migrations/versions/015_entity_item_links.py` | New | `entity_item_links` + `messages` tables, indexes, `llm_calls.correlation_id` column. `down_revision = "014"`. |
| `src/workbench/domain/messages.py` | New | `Message` pydantic model. |
| `src/workbench/domain/__init__.py` | Modify | Export `messages` module. |
| `src/workbench/providers/llm/context.py` | Modify | Add `correlation_id` to `LLMCallContext` + `llm_call_context(...)`. |
| `src/workbench/domain/llm_calls.py` | Modify | Add `correlation_id` to `LlmCallRecord`. |
| `src/workbench/storage/base.py` | Modify | Add `EntityLink` dataclass, `EntityLinkStore` + `MessageStore` ABCs; wire `entity_links`/`messages` into `Stores`; `LlmCallStore.save_many` gains `entity_links` kwarg. |
| `src/workbench/storage/postgres/entity_links.py` | New | `PgEntityLinkStore`. |
| `src/workbench/storage/postgres/messages.py` | New | `PgMessageStore`. |
| `src/workbench/storage/postgres/llm_calls.py` | Modify | `save_many` → `INSERT ... RETURNING id` + link rows; persist `correlation_id`; pruners call `unlink_entity`. |
| `src/workbench/storage/postgres/stores.py` | Modify | Construct `entity_links`, `messages`. |
| `src/workbench/runtime/app.py` | Modify | Sink copies `correlation_id`; `_drain_once` passes `entity_links` into `save_many`. |
| `src/workbench/pipeline/extraction.py` | Modify | Thread root path; stamp `item_paths`. |
| `src/workbench/pipeline/filter.py` | Modify | Stamp `correlation_id`; surface it to caller. |
| `src/workbench/pipeline/engine.py` | Modify | Extraction root path; batched-scoring correlation + record; per-item urgency stamp; `enqueue` surfaces root path. |
| `src/workbench/pipeline/triage.py` | Modify | `generate_card` takes item path; stamps `item_paths`. |
| `src/workbench/pipeline/scheduler.py` | Modify | Batched urgency correlation + record; interpret stamps + record interaction; send sites persist `Message` + record. |
| `src/workbench/api/items.py` | Modify | `GET /api/items/{path}/related`. |
| `ui/src/hooks/useItems.ts` | Modify | `useItemRelated` hook. |
| `ui/src/pages/ItemPage.tsx` | Modify | "What touched this" section + subtree toggle. |

---

### Task 1: Migration 015 — `entity_item_links` + `messages` tables and `llm_calls.correlation_id`

**Files:**
- Create: `src/workbench/migrations/versions/015_entity_item_links.py`
- Test: `tests/test_migration_015.py`

- [ ] Step 1: Write the failing test

`tests/test_migration_015.py`:
```python
"""Round-trip schema test for migration 015 (entity_item_links + messages).

Assumes `alembic upgrade head` has been run so the schema is at 015. Verifies
the new tables, the llm_calls.correlation_id column, and the six entity_item_links
indexes exist, and that an entity_item_links row round-trips with an items FK.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_entity_item_links_table_and_indexes(pg_pool):
    cols = {
        r["column_name"]: r["is_nullable"]
        for r in await pg_pool.fetch(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'entity_item_links'"
        )
    }
    assert cols["entity_type"] == "NO"
    assert cols["entity_id"] == "YES"
    assert cols["item_id"] == "NO"
    assert cols["item_path"] == "NO"
    assert cols["correlation_id"] == "YES"

    idx = {
        r["indexname"]
        for r in await pg_pool.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'entity_item_links'"
        )
    }
    for name in (
        "uq_eil_entity_item",
        "uq_eil_corr_item",
        "idx_eil_entity",
        "idx_eil_path",
        "idx_eil_item",
        "idx_eil_corr",
    ):
        assert name in idx, f"missing index {name}"


async def test_messages_table(pg_pool):
    cols = {
        r["column_name"]
        for r in await pg_pool.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'messages'"
        )
    }
    assert {"id", "kind", "direction", "bot_message_id", "body", "summary", "created_at"} <= cols


async def test_llm_calls_correlation_id_column(pg_pool):
    cols = {
        r["column_name"]
        for r in await pg_pool.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'llm_calls'"
        )
    }
    assert "correlation_id" in cols


async def test_entity_item_links_roundtrip_and_cascade(pg_pool):
    item_id = await pg_pool.fetchval(
        "INSERT INTO items (source_type, source_id, summary, category, origin, "
        "priority, status, path) VALUES "
        "('t','s1','sum','informational','auto_included','P2','active','9001') "
        "RETURNING id"
    )
    link_id = await pg_pool.fetchval(
        "INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path) "
        "VALUES ('llm_call', 1, $1, '9001') RETURNING id",
        item_id,
    )
    assert link_id is not None
    # ON DELETE CASCADE: deleting the item removes the link row.
    await pg_pool.execute("DELETE FROM items WHERE id = $1", item_id)
    remaining = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM entity_item_links WHERE id = $1", link_id
    )
    assert remaining == 0
```

Add `entity_item_links` and `messages` to the `TABLES` list in `tests/conftest.py` so they get TRUNCATEd. Insert them before `"items"` (so cascade order is sane):
```python
TABLES = [
    "funnel_stages",
    "funnel_order",
    "feedback_corrections",
    "filter_tuning_tasks",
    "enrichers",
    "loopbacks",
    "entity_item_links",
    "messages",
    "llm_calls",
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

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_migration_015.py -v --tb=short`
  Expected: errors — `relation "entity_item_links" does not exist` on TRUNCATE in the `pg_pool` fixture (migration not written yet), or assertion failures showing missing columns/indexes.

- [ ] Step 3: Write minimal implementation

`src/workbench/migrations/versions/015_entity_item_links.py`:
```python
"""Cross-entity lineage: generic entity_item_links join table + durable messages.

Adds:
  - entity_item_links: the one bidirectional many-to-many edge table linking any
    entity (llm_call, interaction, plan, triage_card, message) to the item
    path(s) it consumed. item_id has ON DELETE CASCADE; entity_id is nullable to
    support correlation-id rows written before the async record id exists. Two
    partial unique indexes keep id-known and correlation-only rows idempotent.
  - messages: durable record per sent/received message (card, alert, briefing,
    retriage, reply) so a message is a first-class, linkable entity.
  - llm_calls.correlation_id: lets the post-persist path resolve entity_id by
    joining on this column.

Revision ID: 015
Revises: 014
Create Date: 2026-06-18
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_item_links (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_type    TEXT        NOT NULL,
            entity_id      BIGINT      NULL,
            item_id        BIGINT      NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            item_path      TEXT        NOT NULL,
            correlation_id TEXT        NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_eil_entity_item "
        "ON entity_item_links (entity_type, entity_id, item_path) "
        "WHERE entity_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_eil_corr_item "
        "ON entity_item_links (entity_type, correlation_id, item_path) "
        "WHERE correlation_id IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_eil_entity ON entity_item_links (entity_type, entity_id)")
    op.execute("CREATE INDEX idx_eil_path ON entity_item_links (item_path text_pattern_ops)")
    op.execute("CREATE INDEX idx_eil_item ON entity_item_links (item_id)")
    op.execute("CREATE INDEX idx_eil_corr ON entity_item_links (correlation_id)")

    op.execute(
        """
        CREATE TABLE messages (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            kind           TEXT NOT NULL,
            direction      TEXT NOT NULL,
            bot_message_id TEXT NULL,
            body           TEXT NULL,
            summary        TEXT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute("ALTER TABLE llm_calls ADD COLUMN correlation_id TEXT NULL")
    op.execute("CREATE INDEX idx_llm_calls_correlation_id ON llm_calls (correlation_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_llm_calls_correlation_id")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS correlation_id")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS entity_item_links")
```

Then apply the migration: `$HOME/.venv/workbench/bin/python -m alembic upgrade head`

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m alembic upgrade head && $HOME/.venv/workbench/bin/python -m pytest tests/test_migration_015.py -v --tb=short`
  Expected: PASS (4 tests).

- [ ] Step 5: Commit
  `git add src/workbench/migrations/versions/015_entity_item_links.py tests/test_migration_015.py tests/conftest.py && git commit -m "feat(lineage): migration 015 — entity_item_links + messages tables"`

---

### Task 2: Domain — `correlation_id` on context + record, and `Message` model

**Files:**
- Modify: `src/workbench/providers/llm/context.py`
- Modify: `src/workbench/domain/llm_calls.py`
- Create: `src/workbench/domain/messages.py`
- Modify: `src/workbench/domain/__init__.py`
- Test: `tests/test_lineage_domain.py`

- [ ] Step 1: Write the failing test

`tests/test_lineage_domain.py`:
```python
"""Domain additions for cross-entity lineage: correlation_id on the LLM call
context + record, and the new Message model."""

from workbench.providers.llm.context import (
    LLMCallContext,
    llm_call_context,
    current_llm_call_context,
)
from workbench.domain.llm_calls import LlmCallRecord
from workbench.domain.messages import Message
from datetime import datetime, timezone


def test_context_has_correlation_id_default_none():
    ctx = LLMCallContext(origin="o", purpose="p", stage="s")
    assert ctx.correlation_id is None


def test_llm_call_context_helper_stamps_correlation_id():
    with llm_call_context(
        origin="filter", purpose="score_relevance", stage="filter",
        correlation_id="abc-123",
    ):
        ctx = current_llm_call_context()
        assert ctx.correlation_id == "abc-123"
        assert ctx.item_paths == ()


def test_llm_call_record_has_correlation_id():
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o", purpose="p", stage="filter", model="m", status="ok",
        correlation_id="xyz",
    )
    assert rec.correlation_id == "xyz"


def test_message_model_defaults():
    m = Message(kind="card", direction="outbound", summary="card #5")
    assert m.id is None
    assert m.kind == "card"
    assert m.direction == "outbound"
    assert m.bot_message_id is None
    assert isinstance(m.created_at, datetime)


def test_message_exported_from_domain():
    from workbench.domain import Message as DomainMessage
    assert DomainMessage is Message
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_lineage_domain.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench.domain.messages'` (and, once that exists, `TypeError`/`AttributeError` on `correlation_id`).

- [ ] Step 3: Write minimal implementation

In `src/workbench/providers/llm/context.py`, add the field to the dataclass (after `item_paths`):
```python
    origin: str
    purpose: str
    stage: str
    item_paths: tuple[str, ...] = ()
    correlation_id: str | None = None
```
And update the `llm_call_context` helper signature + construction:
```python
@contextmanager
def llm_call_context(
    *,
    origin: str,
    purpose: str,
    stage: str,
    item_paths: tuple[str, ...] | list[str] = (),
    correlation_id: str | None = None,
):
    context = LLMCallContext(
        origin=origin,
        purpose=purpose,
        stage=stage,
        item_paths=tuple(item_paths),
        correlation_id=correlation_id,
    )
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)
```

In `src/workbench/domain/llm_calls.py`, add the field to `LlmCallRecord` (after `is_fallback`):
```python
    is_fallback: bool = False
    correlation_id: str | None = None
```

Create `src/workbench/domain/messages.py`:
```python
"""Durable message entity for cross-entity lineage.

A persisted record per outbound/inbound message (card sends, alerts, briefings,
re-triage pings, replies). Makes a message a first-class, linkable entity rather
than an ephemeral render of a TriageCard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["Message"]


class Message(BaseModel):
    id: int | None = None
    kind: Literal["card", "alert", "briefing", "retriage", "reply"]
    direction: Literal["outbound", "inbound"]
    bot_message_id: str | None = None
    body: str | None = None
    summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

In `src/workbench/domain/__init__.py`, add the import + `__all__` entry. After the `plans` block (line ~28-29) add:
```python
from workbench.domain.messages import *  # noqa: F401,F403
from workbench.domain.messages import __all__ as _messages_all
```
And add `*_messages_all,` to the `__all__` list (alongside `*_plans_all,`).

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_lineage_domain.py -v --tb=short`
  Expected: PASS (5 tests).

- [ ] Step 5: Commit
  `git add src/workbench/providers/llm/context.py src/workbench/domain/llm_calls.py src/workbench/domain/messages.py src/workbench/domain/__init__.py tests/test_lineage_domain.py && git commit -m "feat(lineage): correlation_id on context+record + Message domain model"`

---

### Task 3: Storage base — `EntityLink` dataclass + `EntityLinkStore`/`MessageStore` ABCs + `Stores` wiring

**Files:**
- Modify: `src/workbench/storage/base.py`
- Test: `tests/test_storage_base_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_storage_base_lineage.py`:
```python
"""The lineage store ABCs and Stores container wiring."""

import inspect

from workbench.storage.base import (
    EntityLink,
    EntityLinkStore,
    MessageStore,
    LlmCallStore,
    Stores,
)


def test_entity_link_dataclass_fields():
    link = EntityLink(
        entity_type="llm_call",
        entity_id=7,
        item_id=42,
        item_path="123.1",
        correlation_id=None,
    )
    assert link.entity_type == "llm_call"
    assert link.entity_id == 7
    assert link.item_path == "123.1"


def test_entity_link_store_abstract_methods():
    methods = {
        name for name, _ in inspect.getmembers(EntityLinkStore, inspect.isfunction)
    }
    assert {
        "record",
        "record_by_correlation",
        "unlink_entity",
        "for_item",
        "for_entity",
    } <= methods


def test_message_store_abstract_methods():
    methods = {
        name for name, _ in inspect.getmembers(MessageStore, inspect.isfunction)
    }
    assert {"save", "get_by_id", "list_recent", "delete_older_than"} <= methods


def test_llm_call_store_save_many_accepts_entity_links_kwarg():
    sig = inspect.signature(LlmCallStore.save_many)
    assert "entity_links" in sig.parameters


def test_stores_accepts_entity_links_and_messages():
    sig = inspect.signature(Stores.__init__)
    assert "entity_links" in sig.parameters
    assert "messages" in sig.parameters
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage_base_lineage.py -v --tb=short`
  Expected: `ImportError: cannot import name 'EntityLink' from 'workbench.storage.base'`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/storage/base.py`:

Add `from dataclasses import dataclass` to the top imports, and `from workbench.domain.messages import Message` alongside the other domain imports.

Add the dataclass + ABCs (place them just before the `LlmCallStore` class):
```python
@dataclass(frozen=True)
class EntityLink:
    entity_type: str
    entity_id: int | None
    item_id: int
    item_path: str
    correlation_id: str | None = None
    created_at: datetime | None = None


class EntityLinkStore(ABC):
    @abstractmethod
    async def record(
        self, entity_type: str, entity_id: int, item_paths: list[str]
    ) -> None:
        """Idempotent upsert. Resolves each path to its item_id in-DB and writes
        one row per resolved path (ON CONFLICT DO NOTHING). Empty item_paths is a
        no-op; an unknown path resolves to no row."""
        ...

    @abstractmethod
    async def record_by_correlation(
        self, entity_type: str, correlation_id: str, item_paths: list[str]
    ) -> None:
        """Post-persist path. Same in-DB path->id resolve, but entity_id is left
        NULL and correlation_id is stamped."""
        ...

    @abstractmethod
    async def unlink_entity(self, entity_type: str, entity_id: int) -> int:
        """Delete all link rows for one entity (retention cascade). Returns count."""
        ...

    @abstractmethod
    async def for_item(self, path: str, *, subtree: bool = False) -> list[EntityLink]:
        """All links touching ``path`` (and descendants when subtree=True)."""
        ...

    @abstractmethod
    async def for_entity(
        self, entity_type: str, entity_id: int
    ) -> list[EntityLink]:
        """All item links an entity consumed."""
        ...


class MessageStore(ABC):
    @abstractmethod
    async def save(self, message: Message) -> Message: ...
    @abstractmethod
    async def get_by_id(self, message_id: int) -> Message | None: ...
    @abstractmethod
    async def list_recent(self, limit: int) -> list[Message]: ...
    @abstractmethod
    async def delete_older_than(self, days: int) -> int:
        """Delete messages older than days. Returns count deleted."""
        ...
```

Change the `LlmCallStore.save_many` abstract signature:
```python
class LlmCallStore(ABC):
    @abstractmethod
    async def save_many(
        self, records: list[LlmCallRecord], *, entity_links=None
    ) -> None: ...
```

In `Stores.__init__`, add two new optional kwargs at the end of the keyword-only block (after `llm_calls`):
```python
        llm_calls: LlmCallStore | None = None,
        entity_links: EntityLinkStore | None = None,
        messages: MessageStore | None = None,
    ):
```
and assign them in the body (after `self.llm_calls = llm_calls`):
```python
        self.llm_calls = llm_calls
        self.entity_links = entity_links
        self.messages = messages
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage_base_lineage.py -v --tb=short`
  Expected: PASS (5 tests).

- [ ] Step 5: Commit
  `git add src/workbench/storage/base.py tests/test_storage_base_lineage.py && git commit -m "feat(lineage): EntityLinkStore + MessageStore ABCs and Stores wiring"`

---

### Task 4: `PgEntityLinkStore`

**Files:**
- Create: `src/workbench/storage/postgres/entity_links.py`
- Test: `tests/test_entity_links_store.py`

- [ ] Step 1: Write the failing test

`tests/test_entity_links_store.py`:
```python
"""PgEntityLinkStore: in-DB path resolution, idempotency, correlation rows,
subtree scans, unlink, and reverse lookups."""

import pytest

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.storage.postgres.entity_links import PgEntityLinkStore

pytestmark = pytest.mark.asyncio


async def _make_tree(stores):
    """Build root #N with two children #N.1, #N.2. Returns the three Items."""
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.EXTRACTED,
        )
    )
    c1 = await stores.items.allocate_child(
        root,
        Item(
            source_type="t", source_id="r1", summary="c1",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        ),
    )
    c2 = await stores.items.allocate_child(
        root,
        Item(
            source_type="t", source_id="r1", summary="c2",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        ),
    )
    return root, c1, c2


async def test_record_resolves_paths_to_ids(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 991, [root.path, c1.path])
    links = await els.for_entity("llm_call", 991)
    by_path = {l.item_path: l for l in links}
    assert set(by_path) == {root.path, c1.path}
    assert by_path[root.path].item_id == root.id
    assert by_path[c1.path].item_id == c1.id


async def test_record_is_idempotent(stores, pg_pool):
    root, _, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path])
    await els.record("llm_call", 1, [root.path])
    assert len(await els.for_entity("llm_call", 1)) == 1


async def test_record_unknown_path_writes_no_row(stores, pg_pool):
    root, _, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path, "999999"])
    links = await els.for_entity("llm_call", 1)
    assert {l.item_path for l in links} == {root.path}


async def test_record_empty_is_noop(stores, pg_pool):
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [])
    assert await els.for_entity("llm_call", 1) == []


async def test_record_by_correlation_leaves_entity_id_null(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    rows = await els.for_item(c1.path)
    assert len(rows) == 1
    assert rows[0].entity_id is None
    assert rows[0].correlation_id == "corr-1"


async def test_record_by_correlation_idempotent(stores, pg_pool):
    _, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    await els.record_by_correlation("llm_call", "corr-1", [c1.path])
    assert len(await els.for_item(c1.path)) == 1


async def test_for_item_subtree(stores, pg_pool):
    root, c1, c2 = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 1, [root.path])
    await els.record("llm_call", 2, [c1.path])
    await els.record("llm_call", 3, [c2.path])
    shallow = await els.for_item(root.path, subtree=False)
    assert {l.item_path for l in shallow} == {root.path}
    deep = await els.for_item(root.path, subtree=True)
    assert {l.item_path for l in deep} == {root.path, c1.path, c2.path}


async def test_unlink_entity_deletes_rows(stores, pg_pool):
    root, c1, _ = await _make_tree(stores)
    els = PgEntityLinkStore(pg_pool)
    await els.record("llm_call", 7, [root.path, c1.path])
    n = await els.unlink_entity("llm_call", 7)
    assert n == 2
    assert await els.for_entity("llm_call", 7) == []
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_entity_links_store.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench.storage.postgres.entity_links'`.

- [ ] Step 3: Write minimal implementation

`src/workbench/storage/postgres/entity_links.py`:
```python
from __future__ import annotations

import asyncpg

from workbench.storage.base import EntityLink, EntityLinkStore


class PgEntityLinkStore(EntityLinkStore):
    """The only reader/writer of entity_item_links.

    ``record`` / ``record_by_correlation`` resolve item paths to item ids in one
    round trip (INSERT ... SELECT ... WHERE path = ANY($paths)); an unknown path
    produces no row. Both are idempotent via the partial unique indexes
    (ON CONFLICT DO NOTHING).
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @staticmethod
    def _row(r) -> EntityLink:
        return EntityLink(
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            item_id=r["item_id"],
            item_path=r["item_path"],
            correlation_id=r["correlation_id"],
            created_at=r["created_at"],
        )

    async def record(
        self, entity_type: str, entity_id: int, item_paths: list[str]
    ) -> None:
        if not item_paths:
            return
        await self.pool.execute(
            """INSERT INTO entity_item_links (entity_type, entity_id, item_id, item_path)
               SELECT $1, $2, i.id, i.path FROM items i WHERE i.path = ANY($3::text[])
               ON CONFLICT DO NOTHING""",
            entity_type,
            entity_id,
            list(item_paths),
        )

    async def record_by_correlation(
        self, entity_type: str, correlation_id: str, item_paths: list[str]
    ) -> None:
        if not item_paths:
            return
        await self.pool.execute(
            """INSERT INTO entity_item_links
                 (entity_type, entity_id, item_id, item_path, correlation_id)
               SELECT $1, NULL, i.id, i.path, $2
                 FROM items i WHERE i.path = ANY($3::text[])
               ON CONFLICT DO NOTHING""",
            entity_type,
            correlation_id,
            list(item_paths),
        )

    async def unlink_entity(self, entity_type: str, entity_id: int) -> int:
        res = await self.pool.execute(
            "DELETE FROM entity_item_links WHERE entity_type = $1 AND entity_id = $2",
            entity_type,
            entity_id,
        )
        return int(res.split()[-1])

    async def for_item(self, path: str, *, subtree: bool = False) -> list[EntityLink]:
        if subtree:
            rows = await self.pool.fetch(
                "SELECT * FROM entity_item_links "
                "WHERE item_path = $1 OR item_path LIKE $1 || '.%' "
                "ORDER BY created_at DESC, id DESC",
                path,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM entity_item_links WHERE item_path = $1 "
                "ORDER BY created_at DESC, id DESC",
                path,
            )
        return [self._row(r) for r in rows]

    async def for_entity(
        self, entity_type: str, entity_id: int
    ) -> list[EntityLink]:
        rows = await self.pool.fetch(
            "SELECT * FROM entity_item_links "
            "WHERE entity_type = $1 AND entity_id = $2 "
            "ORDER BY created_at DESC, id DESC",
            entity_type,
            entity_id,
        )
        return [self._row(r) for r in rows]
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_entity_links_store.py -v --tb=short`
  Expected: PASS (8 tests).

- [ ] Step 5: Commit
  `git add src/workbench/storage/postgres/entity_links.py tests/test_entity_links_store.py && git commit -m "feat(lineage): PgEntityLinkStore (record/by_correlation/unlink/for_item/for_entity)"`

---

### Task 5: `PgMessageStore`

**Files:**
- Create: `src/workbench/storage/postgres/messages.py`
- Test: `tests/test_messages_store.py`

- [ ] Step 1: Write the failing test

`tests/test_messages_store.py`:
```python
"""PgMessageStore: save/get/list/delete round-trips for the durable messages
entity."""

import pytest
from datetime import datetime, timezone, timedelta

from workbench.domain.messages import Message
from workbench.storage.postgres.messages import PgMessageStore

pytestmark = pytest.mark.asyncio


async def test_save_assigns_id_and_get_roundtrips(pg_pool):
    ms = PgMessageStore(pg_pool)
    saved = await ms.save(
        Message(kind="card", direction="outbound", body="hello", summary="card #5")
    )
    assert saved.id is not None
    got = await ms.get_by_id(saved.id)
    assert got.kind == "card"
    assert got.direction == "outbound"
    assert got.body == "hello"
    assert got.summary == "card #5"


async def test_get_missing_returns_none(pg_pool):
    ms = PgMessageStore(pg_pool)
    assert await ms.get_by_id(999999) is None


async def test_list_recent_orders_newest_first(pg_pool):
    ms = PgMessageStore(pg_pool)
    a = await ms.save(Message(kind="alert", direction="outbound", summary="a"))
    b = await ms.save(Message(kind="card", direction="outbound", summary="b"))
    recent = await ms.list_recent(10)
    assert [m.id for m in recent[:2]] == [b.id, a.id]


async def test_delete_older_than(pg_pool):
    ms = PgMessageStore(pg_pool)
    saved = await ms.save(Message(kind="reply", direction="inbound", summary="r"))
    await pg_pool.execute(
        "UPDATE messages SET created_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=40),
        saved.id,
    )
    deleted = await ms.delete_older_than(28)
    assert deleted == 1
    assert await ms.get_by_id(saved.id) is None
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_messages_store.py -v --tb=short`
  Expected: `ModuleNotFoundError: No module named 'workbench.storage.postgres.messages'`.

- [ ] Step 3: Write minimal implementation

`src/workbench/storage/postgres/messages.py`:
```python
from __future__ import annotations

import asyncpg

from workbench.domain.messages import Message
from workbench.storage.base import MessageStore


class PgMessageStore(MessageStore):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @staticmethod
    def _row(r) -> Message:
        return Message(
            id=r["id"],
            kind=r["kind"],
            direction=r["direction"],
            bot_message_id=r["bot_message_id"],
            body=r["body"],
            summary=r["summary"],
            created_at=r["created_at"],
        )

    async def save(self, message: Message) -> Message:
        row = await self.pool.fetchrow(
            """INSERT INTO messages (kind, direction, bot_message_id, body, summary)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, kind, direction, bot_message_id, body, summary, created_at""",
            message.kind,
            message.direction,
            message.bot_message_id,
            message.body,
            message.summary,
        )
        return self._row(row)

    async def get_by_id(self, message_id: int) -> Message | None:
        r = await self.pool.fetchrow("SELECT * FROM messages WHERE id = $1", message_id)
        return self._row(r) if r else None

    async def list_recent(self, limit: int) -> list[Message]:
        rows = await self.pool.fetch(
            "SELECT * FROM messages ORDER BY created_at DESC, id DESC LIMIT $1", limit
        )
        return [self._row(r) for r in rows]

    async def delete_older_than(self, days: int) -> int:
        res = await self.pool.execute(
            "DELETE FROM messages WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(res.split()[-1])
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_messages_store.py -v --tb=short`
  Expected: PASS (4 tests).

- [ ] Step 5: Commit
  `git add src/workbench/storage/postgres/messages.py tests/test_messages_store.py && git commit -m "feat(lineage): PgMessageStore for the durable messages entity"`

---

### Task 6: `save_many` writes link rows + persists `correlation_id`; pruners call `unlink_entity`

**Files:**
- Modify: `src/workbench/storage/postgres/llm_calls.py`
- Test: `tests/test_llm_calls_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_llm_calls_lineage.py`:
```python
"""save_many writes entity_item_links rows for call-time records (those with
items), persists correlation_id, and the retention pruners cascade-unlink."""

import pytest
from datetime import datetime, timezone, timedelta

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.domain.llm_calls import LlmCallRecord
from workbench.storage.postgres.entity_links import PgEntityLinkStore

pytestmark = pytest.mark.asyncio


async def _root(stores, source_id):
    return await stores.items.create_root(
        Item(
            source_type="t", source_id=source_id, summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.EXTRACTED,
        )
    )


def _rec(items=None, correlation_id=None, started=None):
    return LlmCallRecord(
        started_at=started or datetime.now(timezone.utc),
        origin="o", purpose="p", stage="filter", model="m", status="ok",
        items=items or [], correlation_id=correlation_id,
    )


async def test_save_many_writes_links_for_call_time_records(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many([_rec(items=[root.path])], entity_links=els)
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(calls) == 1
    links = await els.for_entity("llm_call", calls[0].id)
    assert {l.item_path for l in links} == {root.path}


async def test_save_many_no_links_for_correlation_records(stores, pg_pool):
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many(
        [_rec(items=[], correlation_id="corr-1")], entity_links=els
    )
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(calls) == 1
    # correlation_id persisted on the row, but NO link rows written here.
    got = await stores.llm_calls.get_by_id(calls[0].id)
    assert got.correlation_id == "corr-1"
    assert await els.for_entity("llm_call", calls[0].id) == []


async def test_save_many_without_entity_links_still_persists(stores):
    root_paths = []
    await stores.llm_calls.save_many([_rec(items=root_paths)])
    assert len(await stores.llm_calls.list_calls(limit=10)) == 1


async def test_delete_older_than_unlinks(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many([_rec(items=[root.path])], entity_links=els)
    calls = await stores.llm_calls.list_calls(limit=10)
    assert len(await els.for_entity("llm_call", calls[0].id)) == 1
    # delete_older_than filters on created_at (server-default now(), not inserted
    # by save_many), so age that column directly to make the row eligible.
    await pg_pool.execute(
        "UPDATE llm_calls SET created_at = $1 WHERE id = $2",
        datetime.now(timezone.utc) - timedelta(days=40),
        calls[0].id,
    )
    await stores.llm_calls.delete_older_than(28, entity_links=els)
    assert await els.for_entity("llm_call", calls[0].id) == []


async def test_prune_to_max_rows_unlinks(stores, pg_pool):
    root = await _root(stores, "r1")
    els = PgEntityLinkStore(pg_pool)
    await stores.llm_calls.save_many(
        [
            _rec(items=[root.path], started=datetime.now(timezone.utc) - timedelta(minutes=3)),
            _rec(items=[root.path], started=datetime.now(timezone.utc) - timedelta(minutes=1)),
        ],
        entity_links=els,
    )
    calls = await stores.llm_calls.list_calls(limit=10)
    oldest = calls[-1].id
    deleted = await stores.llm_calls.prune_to_max_rows(1, entity_links=els)
    assert deleted == 1
    assert await els.for_entity("llm_call", oldest) == []
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_llm_calls_lineage.py -v --tb=short`
  Expected: `TypeError: save_many() got an unexpected keyword argument 'entity_links'`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/storage/postgres/llm_calls.py`, replace `save_many` with an `INSERT ... RETURNING id` loop that also writes link rows, persists `correlation_id`, and updates the pruner signatures. Replace the whole `save_many` method:
```python
    async def save_many(self, records, *, entity_links=None) -> None:
        if not records:
            return
        async with self.pool.acquire() as conn:
            for r in records:
                new_id = await conn.fetchval(
                    """INSERT INTO llm_calls
                       (started_at,origin,purpose,stage,model,temperature,status,error_type,
                        batch,items,tokens_in,tokens_out,cache_read_tokens,cache_write_tokens,
                        latency_ms,system_prompt,subcalls,tokens_estimated,is_fallback,
                        correlation_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,
                               $17::jsonb,$18,$19,$20)
                       RETURNING id""",
                    r.started_at,
                    r.origin,
                    r.purpose,
                    r.stage,
                    r.model,
                    r.temperature,
                    r.status,
                    r.error_type,
                    r.batch,
                    json.dumps(r.items),
                    r.tokens_in,
                    r.tokens_out,
                    r.cache_read_tokens,
                    r.cache_write_tokens,
                    r.latency_ms,
                    r.system_prompt,
                    json.dumps([s.model_dump() for s in r.subcalls]),
                    r.tokens_estimated,
                    r.is_fallback,
                    r.correlation_id,
                )
                # Call-time link rows: only records that carry item paths. Records
                # with a correlation_id (post-persist path) write NO link rows here
                # -- those arrive via record_by_correlation once the items exist.
                if entity_links is not None and r.items:
                    await entity_links.record("llm_call", new_id, list(r.items))
```

In `_row`, add `correlation_id` handling so reads round-trip (it is already in `dict(rec)` since the column exists; no change needed beyond ensuring `LlmCallRecord(**d)` accepts it — it does after Task 2).

Update `delete_older_than` to unlink first:
```python
    async def delete_older_than(self, days, *, entity_links=None) -> int:
        if entity_links is not None:
            ids = await self.pool.fetch(
                "SELECT id FROM llm_calls WHERE created_at < NOW() - INTERVAL '1 day' * $1",
                days,
            )
            for row in ids:
                await entity_links.unlink_entity("llm_call", row["id"])
        res = await self.pool.execute(
            "DELETE FROM llm_calls WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            days,
        )
        return int(res.split()[-1])
```

Update `prune_to_max_rows`:
```python
    async def prune_to_max_rows(self, max_rows, *, entity_links=None) -> int:
        victims = await self.pool.fetch(
            "SELECT id FROM llm_calls ORDER BY started_at DESC OFFSET $1", max_rows
        )
        if entity_links is not None:
            for row in victims:
                await entity_links.unlink_entity("llm_call", row["id"])
        res = await self.pool.execute(
            "DELETE FROM llm_calls WHERE id IN "
            "(SELECT id FROM llm_calls ORDER BY started_at DESC OFFSET $1)",
            max_rows,
        )
        return int(res.split()[-1])
```

(Note: the entity-side unlink is code-owned; the item-side `ON DELETE CASCADE` does not help when deleting an llm_call, hence these explicit unlinks.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_llm_calls_lineage.py tests/test_llm_calls_store.py -v --tb=short`
  Expected: PASS (new file 5 tests; existing store tests still green — they call `save_many` without `entity_links`, which now defaults to None).

- [ ] Step 5: Commit
  `git add src/workbench/storage/postgres/llm_calls.py tests/test_llm_calls_lineage.py && git commit -m "feat(lineage): save_many writes link rows + persists correlation_id; pruners unlink"`

---

### Task 7: `stores.py` wiring + `app.py` sink/drain plumbing

**Files:**
- Modify: `src/workbench/storage/postgres/stores.py`
- Modify: `src/workbench/runtime/app.py`
- Test: `tests/test_lineage_wiring.py`

- [ ] Step 1: Write the failing test

`tests/test_lineage_wiring.py`:
```python
"""stores.entity_links / stores.messages are constructed, the sink copies
correlation_id onto the record, and _drain_once passes entity_links into
save_many."""

import asyncio
import pytest
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import LLMCallContext
from workbench.providers.llm.plugboard import PlugboardCallRecord
from workbench.runtime.app import _to_llm_record, _drain_once

pytestmark = pytest.mark.asyncio


async def test_stores_construct_entity_links_and_messages(stores):
    assert stores.entity_links is not None
    assert stores.messages is not None


def test_to_llm_record_copies_correlation_id():
    rec = PlugboardCallRecord(
        client="plugboard",
        model="m",
        context=LLMCallContext(
            origin="filter", purpose="score_relevance", stage="filter",
            correlation_id="corr-9",
        ),
    )
    out = _to_llm_record(rec)
    assert out.correlation_id == "corr-9"


async def test_drain_once_passes_entity_links_to_save_many():
    q = asyncio.Queue()
    rec = MagicMock()
    await q.put(rec)
    store = MagicMock()
    store.save_many = AsyncMock()
    links = object()
    await _drain_once(q, store, entity_links=links, max_batch=10)
    store.save_many.assert_awaited_once()
    _, kwargs = store.save_many.call_args
    assert kwargs["entity_links"] is links
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_lineage_wiring.py -v --tb=short`
  Expected: `AttributeError: 'Stores' object has no attribute 'entity_links'` is satisfied (it returns None after Task 3) but `assert stores.entity_links is not None` fails; `_to_llm_record` does not set `correlation_id`; `_drain_once` has no `entity_links` param (`TypeError`).

- [ ] Step 3: Write minimal implementation

In `src/workbench/storage/postgres/stores.py`, add imports and construct the two stores:
```python
from workbench.storage.postgres.entity_links import PgEntityLinkStore
from workbench.storage.postgres.messages import PgMessageStore
```
And in the `Stores(...)` call (after `llm_calls=PgLlmCallStore(pool),`):
```python
        llm_calls=PgLlmCallStore(pool),
        entity_links=PgEntityLinkStore(pool),
        messages=PgMessageStore(pool),
    )
```

In `src/workbench/runtime/app.py`, in `_to_llm_record`, add `correlation_id` to the returned `LlmCallRecord(...)` (after `is_fallback=rec.is_fallback,`):
```python
        is_fallback=rec.is_fallback,
        correlation_id=(rec.context.correlation_id if rec.context else None),
    )
```

Change `_drain_once` to accept and forward `entity_links`:
```python
async def _drain_once(
    queue: asyncio.Queue, store, *, entity_links=None, max_batch: int = 50
) -> None:
    first = await queue.get()
    batch = [first]
    try:
        for _ in range(max_batch):
            batch.append(queue.get_nowait())
    except asyncio.QueueEmpty:
        pass

    records = [r for r in batch if r is not None]
    try:
        if records:
            await store.save_many(records, entity_links=entity_links)
    except Exception:
        logger.exception("llm_calls writer failed; dropping batch")
    finally:
        for _ in batch:
            queue.task_done()
```

In the `_llm_writer_loop` inside `lifespan`, pass `entity_links`:
```python
            async def _llm_writer_loop():
                try:
                    while True:
                        await _drain_once(
                            _q,
                            app.state.stores.llm_calls,
                            entity_links=app.state.stores.entity_links,
                            max_batch=50,
                        )
                except asyncio.CancelledError:
                    return
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_lineage_wiring.py tests/test_llm_writer.py -v --tb=short`
  Expected: PASS. (`test_llm_writer.py` may call `_drain_once(q, store)` positionally without `entity_links`; the new keyword-only param defaults to None so it stays green. If any existing call passed `max_batch` positionally it must be updated to keyword — verify and fix if the run reports a TypeError.)

- [ ] Step 5: Commit
  `git add src/workbench/storage/postgres/stores.py src/workbench/runtime/app.py tests/test_lineage_wiring.py && git commit -m "feat(lineage): wire entity_links/messages stores; sink+drain plumbing"`

---

### Task 8: Bug fix — extraction stamps the root path (call-time)

**Files:**
- Modify: `src/workbench/pipeline/extraction.py`
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_extraction_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_extraction_lineage.py`:
```python
"""extract_items stamps item_paths=(root_path,) so the extraction LLM call links
the root (regression for the empty-items bug)."""

import pytest
from unittest.mock import AsyncMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.pipeline.extraction import extract_items

pytestmark = pytest.mark.asyncio


async def test_extract_items_stamps_root_path():
    captured = {}

    async def fake_extract(raw_text, source_type):
        captured["ctx"] = current_llm_call_context()
        return []

    llm = AsyncMock()
    llm.extract = fake_extract
    await extract_items(llm, "some long enough raw text", "diff", root_path="123")
    assert captured["ctx"].item_paths == ("123",)


async def test_extract_items_no_root_path_stamps_empty():
    captured = {}

    async def fake_extract(raw_text, source_type):
        captured["ctx"] = current_llm_call_context()
        return []

    llm = AsyncMock()
    llm.extract = fake_extract
    await extract_items(llm, "some long enough raw text", "diff")
    assert captured["ctx"].item_paths == ()
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_extraction_lineage.py -v --tb=short`
  Expected: `TypeError: extract_items() got an unexpected keyword argument 'root_path'`.

- [ ] Step 3: Write minimal implementation

`src/workbench/pipeline/extraction.py`:
```python
from workbench.providers.llm.base import LLMProvider
from workbench.providers.llm.context import llm_call_context
from workbench.domain import ExtractedItem


async def extract_items(
    llm: LLMProvider, raw_text: str, source_type: str, *, root_path: str | None = None
) -> list[ExtractedItem]:
    if not raw_text or len(raw_text.strip()) < 10:
        return []
    with llm_call_context(
        origin="extract",
        purpose="extract",
        stage="extract",
        item_paths=((root_path,) if root_path else ()),
    ):
        return await llm.extract(raw_text, source_type)
```

In `src/workbench/pipeline/engine.py::process_raw_item`, the root is currently resolved AFTER extraction. To stamp the root path at call time, resolve it BEFORE `extract_items` and pass it in. Replace the extraction block:
```python
        try:
            # Resolve the ingestion root first so the extraction call can link it
            # at true depth (call-time path). The root was born in enqueue.
            root = await self.stores.items.get_item_by_source_id(
                raw_item.source_type, raw_item.id
            )
            extracted = await extract_items(
                self.llm,
                raw_item.raw_text,
                raw_item.source_type,
                root_path=(root.path if root else None),
            )
            if job:
                job.items_extracted = len(extracted)
                await self.stores.jobs.update_job(job)
```
and DELETE the later duplicate `root = await self.stores.items.get_item_by_source_id(...)` resolution (the one currently sitting just above the `precomputed = ...` block) so `root` is resolved exactly once.

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_extraction_lineage.py -v --tb=short`
  Expected: PASS (2 tests).

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/extraction.py src/workbench/pipeline/engine.py tests/test_extraction_lineage.py && git commit -m "fix(lineage): extraction stamps the root path so its LLM call links #root"`

---

### Task 9: Bug fix — batched relevance scoring links children via correlation_id (post-persist)

**Files:**
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_batched_scoring_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_batched_scoring_lineage.py`:
```python
"""Batched relevance scoring stamps a correlation_id on the score_relevance_many
call (NOT the root path), and after children are allocated the engine calls
record_by_correlation for the depth-1 child paths (regression for the
mis-stamped-root bug)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import (
    Item, ItemCategory, ItemOrigin, Priority, ItemStatus, RawItem, JobStatus,
    JobTrigger, PipelineJob,
)
from workbench.pipeline.engine import PipelineEngine

pytestmark = pytest.mark.asyncio


async def test_batched_scoring_uses_correlation_and_records_children(stores):
    # Root born like enqueue would.
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.INGESTED,
        )
    )

    captured = {}

    async def fake_score_many(ctx_for_scoring, max_batch_size):
        captured["ctx"] = current_llm_call_context()
        # two items -> both auto_include (high relevance, high confidence)
        return [(90, 90)] * len(ctx_for_scoring)

    llm = MagicMock()
    llm.score_relevance_many = fake_score_many

    memory = AsyncMock()
    memory.query_preferences = AsyncMock(return_value=[])
    memory.query_entity = AsyncMock(return_value=None)
    memory.query_relationships = AsyncMock(return_value=[])
    memory.record_pipeline_decision = AsyncMock()

    eng = PipelineEngine(
        stores, memory, llm, AsyncMock(),
        batch_relevance=True, max_batch_size=20,
    )

    raw = RawItem(source_type="t", source_id="r1", source_label="", raw_text="x" * 50)
    job = PipelineJob(trigger=JobTrigger.MANUAL, status=JobStatus.QUEUED, input_hash="h")
    await stores.jobs.save_job(job)

    # Two extracted items -> two depth-1 children.
    llm_extract = [
        MagicMock(summary="c1", category=ItemCategory.INFORMATIONAL, source_context=""),
        MagicMock(summary="c2", category=ItemCategory.INFORMATIONAL, source_context=""),
    ]

    import workbench.pipeline.engine as engine_mod
    orig = engine_mod.extract_items
    async def fake_extract(llm, raw_text, source_type, *, root_path=None):
        return llm_extract
    engine_mod.extract_items = fake_extract
    try:
        await eng.process_raw_item(raw, job.id)
    finally:
        engine_mod.extract_items = orig

    # The batched call carried a correlation_id, not the root path.
    assert captured["ctx"].item_paths == ()
    assert captured["ctx"].correlation_id is not None

    # After allocation, link rows exist for the two children via correlation_id.
    rows = await stores.entity_links.for_item(root.path, subtree=True)
    child_paths = {r.item_path for r in rows if r.correlation_id == captured["ctx"].correlation_id}
    assert child_paths == {f"{root.path}.1", f"{root.path}.2"}
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_batched_scoring_lineage.py -v --tb=short`
  Expected: assertion failure — `captured["ctx"].item_paths == (root.path,)` (the current mis-stamped root), `correlation_id is None`, and no correlation link rows.

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/engine.py`:

Add `import uuid` to the top imports.

Replace the batched-scoring block (the `with llm_call_context(... item_paths=((root.path,) if root else ()))` wrapper) so it stamps a `correlation_id` instead of the root path, and capture it:
```python
            precomputed: list[tuple[int, int] | None] = [None] * len(items)
            scoring_correlation_id: str | None = None
            if self.batch_relevance and items:
                contexts = await asyncio.gather(
                    *(
                        gather_facts_and_rules(
                            self.memory, self.stores.filter_rules, it
                        )
                        for it in items
                    )
                )
                ctx_for_scoring = [
                    (it, facts, rules) for it, (facts, rules) in zip(items, contexts)
                ]
                scoring_correlation_id = str(uuid.uuid4())
                with llm_call_context(
                    origin="filter",
                    purpose="score_relevance",
                    stage="filter",
                    correlation_id=scoring_correlation_id,
                ):
                    precomputed = await self.llm.score_relevance_many(
                        ctx_for_scoring, max_batch_size=self.max_batch_size
                    )
```

Thread the correlation id into per-item processing so the child path can be recorded after allocation. Change the loop:
```python
            child_paths: list[str] = []
            for ext_item, score in zip(items, precomputed):
                try:
                    child = await self._process_extracted_item(
                        ext_item, job, precomputed=score, root=root
                    )
                    if child is not None and child.path:
                        child_paths.append(child.path)
                except Exception as e:
                    logger.error(f"Failed to process extracted item: {e}")
                    if job:
                        job.items_failed += 1
                        await self.stores.jobs.update_job(job)

            # Post-persist link: the batched scoring call consumed exactly these
            # depth-1 children, born above. Link them by correlation_id (ADR 0064).
            if (
                scoring_correlation_id is not None
                and child_paths
                and self.stores.entity_links is not None
            ):
                await self.stores.entity_links.record_by_correlation(
                    "llm_call", scoring_correlation_id, child_paths
                )
```

Make `_process_extracted_item` RETURN the allocated child Item (it currently returns None). At each of the three `if root is not None: item = await self.stores.items.allocate_child(...)` branches the local `item` already holds the allocated child; add `return item` at the end of the method:
```python
            await self.stores.triage.save_card(card)
            if job:
                job.items_triaged += 1
                await self.stores.jobs.update_job(job)
        return item
```
(Place the single `return item` as the last statement of `_process_extracted_item`, dedented to method level so all three branches return the allocated/saved item.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_batched_scoring_lineage.py tests/test_batching.py -v --tb=short`
  Expected: PASS (new test; existing batching tests still green).

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/engine.py tests/test_batched_scoring_lineage.py && git commit -m "fix(lineage): batched relevance scoring links children via correlation_id"`

---

### Task 10: Bug fix — non-batched `score_and_decide` links its child via correlation_id (post-persist)

**Files:**
- Modify: `src/workbench/pipeline/filter.py`
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_simple_scoring_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_simple_scoring_lineage.py`:
```python
"""Non-batched score_and_decide stamps a correlation_id and returns it so the
caller can record_by_correlation the one child path after allocate_child
(regression for the empty-items bug on the simple site)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem, ExtractedItem, ItemCategory
from workbench.pipeline.filter import score_and_decide

pytestmark = pytest.mark.asyncio


async def test_score_and_decide_stamps_and_returns_correlation_id():
    captured = {}

    async def fake_score(item, facts, rules):
        captured["ctx"] = current_llm_call_context()
        return 90, 90

    llm = MagicMock()
    llm.score_relevance = fake_score

    memory = AsyncMock()
    memory.query_preferences = AsyncMock(return_value=[])
    memory.query_entity = AsyncMock(return_value=None)
    memory.query_relationships = AsyncMock(return_value=[])

    rules = AsyncMock()
    rules.get_rules = AsyncMock(return_value=[])
    rules.get_source_rules = AsyncMock(return_value=[])

    raw = RawItem(source_type="t", source_id="s1", source_label="", raw_text="x")
    item = ExtractedItem(summary="c", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw)

    action, relevance, confidence, correlation_id = await score_and_decide(
        llm, memory, rules, item
    )
    assert action == "auto_include"
    assert correlation_id is not None
    assert captured["ctx"].correlation_id == correlation_id
    assert captured["ctx"].item_paths == ()
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_simple_scoring_lineage.py -v --tb=short`
  Expected: `ValueError: not enough values to unpack (expected 4, got 3)` (it currently returns a 3-tuple).

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/filter.py`, add `import uuid` at the top and change `score_and_decide` to mint + stamp + return a `correlation_id`:
```python
async def score_and_decide(
    llm: LLMProvider,
    memory: MemoryLayer,
    filter_rules: FilterRuleStore,
    item: ExtractedItem,
    include_threshold: int = 70,
    drop_threshold: int = 30,
    confidence_threshold: int = 70,
) -> tuple[str, int, int, str]:
    """Returns (action, relevance, confidence, correlation_id).

    The scored child is minted by the caller AFTER this call (allocate_child), so
    the consumed item path is not known here. Stamp a correlation_id (ADR 0064)
    and return it so the caller can record_by_correlation once the child exists.
    """
    all_facts, all_rules = await gather_facts_and_rules(memory, filter_rules, item)

    correlation_id = str(uuid.uuid4())
    with llm_call_context(
        origin="filter",
        purpose="score_relevance",
        stage="filter",
        correlation_id=correlation_id,
    ):
        relevance, confidence = await llm.score_relevance(item, all_facts, all_rules)

    action = decide_from_score(
        relevance,
        confidence,
        include_threshold=include_threshold,
        drop_threshold=drop_threshold,
        confidence_threshold=confidence_threshold,
    )
    return action, relevance, confidence, correlation_id
```

In `src/workbench/pipeline/engine.py::_process_extracted_item`, update the non-batched branch to capture the correlation id and record it after the child is allocated. Change the `else:` (non-precomputed) branch:
```python
        simple_correlation_id: str | None = None
        if precomputed is not None:
            relevance, confidence = precomputed
            action = decide_from_score(
                relevance,
                confidence,
                include_threshold=include_t,
                drop_threshold=drop_t,
                confidence_threshold=confidence_t,
            )
        else:
            action, relevance, confidence, simple_correlation_id = await score_and_decide(
                self.llm,
                self.memory,
                self.stores.filter_rules,
                ext_item,
                include_threshold=include_t,
                drop_threshold=drop_t,
                confidence_threshold=confidence_t,
            )
```
Then, immediately before the final `return item` you added in Task 9, record the simple-site link:
```python
        if (
            simple_correlation_id is not None
            and item is not None
            and item.path
            and self.stores.entity_links is not None
        ):
            await self.stores.entity_links.record_by_correlation(
                "llm_call", simple_correlation_id, [item.path]
            )
        return item
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_simple_scoring_lineage.py tests/test_batched_scoring_lineage.py -v --tb=short`
  Expected: PASS. (If any other test imports `score_and_decide` expecting a 3-tuple, update it to unpack 4; search with `grep -rn "score_and_decide" tests/ src/` and fix call sites.)

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/filter.py src/workbench/pipeline/engine.py tests/test_simple_scoring_lineage.py tests/test_pipeline.py tests/test_llm_capture_integration.py && git commit -m "fix(lineage): non-batched scoring links its child via correlation_id"`

---

### Task 11: Bug fix — `generate_card` stamps the item path + triage_card link (call-time)

**Files:**
- Modify: `src/workbench/pipeline/triage.py`
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_generate_card_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_generate_card_lineage.py`:
```python
"""generate_card stamps item_paths=(item_path,) on its LLM call (regression for
the unstamped bug); the engine records a triage_card link at the card's item
path after save_card."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem, ExtractedItem, ItemCategory, TriageCard
from workbench.pipeline.triage import generate_card

pytestmark = pytest.mark.asyncio


async def test_generate_card_stamps_item_path():
    captured = {}

    async def fake_card(item, ctx, source_type, memory_context=None, change_context=None):
        captured["ctx"] = current_llm_call_context()
        return TriageCard(card_content={"summary": "s"})

    llm = MagicMock()
    llm.generate_triage_card = fake_card

    raw = RawItem(source_type="t", source_id="s1", source_label="", raw_text="x")
    item = ExtractedItem(summary="c", category=ItemCategory.INFORMATIONAL, source_context="", raw_item=raw)

    await generate_card(llm, item, {"context": {}}, "t", item_path="123.1")
    assert captured["ctx"].item_paths == ("123.1",)
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_generate_card_lineage.py -v --tb=short`
  Expected: `TypeError: generate_card() got an unexpected keyword argument 'item_path'`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/triage.py::generate_card`, add an `item_path: str | None = None` keyword param and stamp it on the existing `llm_call_context`:
```python
async def generate_card(
    llm: LLMProvider,
    item: ExtractedItem,
    enrichment_context: dict,
    source_type: str,
    *,
    memory=None,
    content_generators: dict | None = None,
    change_context: ChangeContext | None = None,
    item_path: str | None = None,
) -> TriageCard:
```
and change the wrapper:
```python
    with llm_call_context(
        origin="triage",
        purpose="generate_card",
        stage="triage",
        item_paths=((item_path,) if item_path else ()),
    ):
```

In `src/workbench/pipeline/engine.py::_process_extracted_item`, the triage branch already has the allocated `item` in scope before `generate_card`. Pass the path and record the triage_card link after `save_card`:
```python
            card = await generate_card(
                self.llm,
                ext_item,
                enrichment,
                ext_item.raw_item.source_type,
                memory=self.memory,
                content_generators=self.content_generators,
                item_path=item.path,
            )
            card.item_id = item.id
            card.relevance_score = relevance
            card.confidence_score = confidence
            card.expires_at = datetime.now(timezone.utc) + timedelta(
                days=self.triage_expiry_days
            )
            saved_card = await self.stores.triage.save_card(card)
            if (
                item.path
                and self.stores.entity_links is not None
                and saved_card.id is not None
            ):
                await self.stores.entity_links.record(
                    "triage_card", saved_card.id, [item.path]
                )
            if job:
                job.items_triaged += 1
                await self.stores.jobs.update_job(job)
```

Also update the re-triage `generate_card` call in `src/workbench/pipeline/scheduler.py` (around line ~499, the `new_card = await generate_card(...)` block) to pass `item_path=item.path` (the `item` is in scope there) so re-triage cards also stamp:
```python
        new_card = await generate_card(
            self.llm,
            ext_item,
            enrichment,
            raw_item.source_type,
            memory=self.memory,
            content_generators=self.content_generators,
            change_context=change_ctx,
            item_path=item.path,
        )
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_generate_card_lineage.py -v --tb=short`
  Expected: PASS.

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/triage.py src/workbench/pipeline/engine.py src/workbench/pipeline/scheduler.py tests/test_generate_card_lineage.py && git commit -m "fix(lineage): generate_card stamps item path + records triage_card link"`

---

### Task 12: Per-item urgency stamps root path; `enqueue` surfaces the minted root path

**Files:**
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_enqueue_urgency_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_enqueue_urgency_lineage.py`:
```python
"""enqueue stamps item_paths=(root.path,) on the per-item score_urgency call and
returns the minted root path alongside the job (so the scheduler can link the
batched urgency call by correlation_id later)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.pipeline.engine import PipelineEngine

pytestmark = pytest.mark.asyncio


async def test_enqueue_returns_root_path(stores):
    eng = PipelineEngine(stores, AsyncMock(), MagicMock(), AsyncMock())
    job, root_path = await eng.enqueue("hello world raw text", "t", source_id="s1")
    assert root_path is not None
    root = await stores.items.get_by_path(root_path)
    assert root is not None and root.source_id == "s1"


async def test_enqueue_per_item_urgency_stamps_root_path(stores):
    captured = {}

    scorer = MagicMock()

    async def fake_score_urgency(raw_text, signals):
        captured["ctx"] = current_llm_call_context()
        return 70

    scorer.score_urgency = fake_score_urgency

    eng = PipelineEngine(stores, AsyncMock(), MagicMock(), AsyncMock(), queue_scorer=scorer)
    job, root_path = await eng.enqueue(
        "hello world raw text", "t", source_id="s2", urgency_signals={"k": "v"}
    )
    assert captured["ctx"].item_paths == (root_path,)
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_enqueue_urgency_lineage.py -v --tb=short`
  Expected: `TypeError: cannot unpack non-sequence PipelineJob` (enqueue returns a bare job), and the urgency context has empty `item_paths`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/engine.py::enqueue`, change the return type to `tuple[PipelineJob, str | None]`, capture the minted root path, stamp it on the per-item urgency call, and return both.

Update the signature/docstring return and the dedup early-return:
```python
    ) -> tuple[PipelineJob, str | None]:
        """... returns (job, root_path) where root_path is the minted root's
        path (None for ad-hoc enqueues without a source_id, or duplicates)."""
        if source_id:
            if await self.stores.processed.is_processed(source_type, source_id):
                job = PipelineJob(
                    trigger=trigger,
                    status=JobStatus.COMPLETED,
                    input_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
                )
                await self.stores.jobs.save_job(job)
                return job, None
```

Capture the root path from `create_root`:
```python
        root_path: str | None = None
        if source_id:
            root = await self.stores.items.create_root(
                Item(
                    source_type=source_type,
                    source_id=source_id,
                    summary=(raw_text[:200] if raw_text else ""),
                    category=ItemCategory.INFORMATIONAL,
                    origin=ItemOrigin.AUTO_INCLUDED,
                    priority=Priority.PENDING,
                    status=ItemStatus.INGESTED,
                    raw_data={
                        "raw_text": raw_text,
                        "source_type": source_type,
                        "id": source_id,
                    },
                )
            )
            root_path = root.path
```

Stamp the per-item urgency call with the root path:
```python
        if urgency_score is None:
            urgency_score = 50
            if self.queue_scorer and urgency_signals:
                try:
                    with llm_call_context(
                        origin="queue_scorer",
                        purpose="score_urgency",
                        stage="scoring",
                        item_paths=((root_path,) if root_path else ()),
                    ):
                        urgency_score = await self.queue_scorer.score_urgency(
                            raw_text, urgency_signals
                        )
                except Exception as e:
                    logger.warning(f"Queue scorer failed, using default: {e}")
```

Return the tuple at the end:
```python
        if source_id:
            await self.stores.processed.mark_processed(source_type, source_id)

        return job, root_path
```

Search for and fix every other caller of `enqueue` that expects a bare job: `grep -rn "\.enqueue(" src/workbench tests`. The scheduler `_enqueue_with_urgency` caller is handled in Task 13. Any API/route or test that calls `pipeline.enqueue(...)` and uses the return must unpack `job, _`. (The `process` API and manual-enqueue endpoints are the likely sites — update them to `job, _ = await ...enqueue(...)`.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_enqueue_urgency_lineage.py -v --tb=short`
  Expected: PASS.

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/engine.py src/workbench/api/process.py tests/test_enqueue_urgency_lineage.py tests/test_api.py tests/test_pipeline.py tests/test_storage.py tests/test_health_counts.py tests/test_stats_api.py && git commit -m "feat(lineage): per-item urgency stamps root path; enqueue surfaces root path"`

---

### Task 13: Batched urgency links roots via correlation_id (post-persist)

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_batched_urgency_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_batched_urgency_lineage.py`:
```python
"""_enqueue_with_urgency stamps a correlation_id on the batched score_urgency_many
call and, after enqueue births the roots, records the roots by correlation_id."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from workbench.providers.llm.context import current_llm_call_context
from workbench.domain import RawItem

pytestmark = pytest.mark.asyncio


async def _scheduler(stores):
    from workbench.pipeline.scheduler import WorkbenchScheduler
    from workbench.config import load_config_defaults  # if present; else build a config
    # Build a minimal config with batching enabled.
    config = MagicMock()
    config.batching.enabled = True
    config.batching.score_urgency = True
    config.batching.max_batch_size = 20

    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    sched.config = config
    sched.pipeline = MagicMock()
    return sched


async def test_batched_urgency_records_roots_by_correlation(stores):
    captured = {}

    scorer = MagicMock()

    async def fake_score_many(pairs, max_batch_size):
        captured["ctx"] = current_llm_call_context()
        return [60] * len(pairs)

    scorer.score_urgency_many = fake_score_many

    sched = await _scheduler(stores)
    sched.pipeline.queue_scorer = scorer

    # enqueue births a root per item; return (job, root_path).
    minted = {"r1": "501", "r2": "502"}

    async def fake_enqueue(raw_text, source_type, *, source_id, urgency_signals,
                           trigger, urgency_score, source_ref, source_url):
        return (MagicMock(), minted[source_id])

    sched.pipeline.enqueue = fake_enqueue

    items = [
        (RawItem(source_type="t", source_id="r1", source_label="", raw_text="a",
                 urgency_signals={"k": 1}), "r1"),
        (RawItem(source_type="t", source_id="r2", source_label="", raw_text="b",
                 urgency_signals={"k": 2}), "r2"),
    ]

    # Pre-create the roots at the minted paths so record_by_correlation resolves them.
    from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
    for sid, path in minted.items():
        await stores.items.pool.execute(
            "INSERT INTO items (source_type, source_id, summary, category, origin, "
            "priority, status, path) VALUES ('t',$1,'r','informational',"
            "'auto_included','P2','ingested',$2)",
            sid, path,
        )

    from workbench.domain.pipeline import JobTrigger
    await sched._enqueue_with_urgency(items, JobTrigger.MANUAL)

    corr = captured["ctx"].correlation_id
    assert corr is not None
    rows_501 = await stores.entity_links.for_item("501")
    rows_502 = await stores.entity_links.for_item("502")
    assert any(r.correlation_id == corr for r in rows_501)
    assert any(r.correlation_id == corr for r in rows_502)
```

(If `WorkbenchScheduler.__new__` bypass is brittle in this repo, instead construct it through its normal constructor with mocks; the load-bearing behavior under test is `_enqueue_with_urgency`.)

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_batched_urgency_lineage.py -v --tb=short`
  Expected: `correlation_id is None` and no correlation link rows (the batched urgency call is currently unstamped and roots are never recorded).

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py`, add `import uuid` near the top imports if not present. Rewrite `_enqueue_with_urgency` so it (a) stamps a `correlation_id` on the batched call, (b) collects minted root paths from `enqueue`'s now-tuple return, and (c) records by correlation after the loop:
```python
    async def _enqueue_with_urgency(self, items, trigger) -> int:
        if not items:
            return 0
        batching = self.config.batching
        scorer = getattr(self.pipeline, "queue_scorer", None)
        prescored: dict[int, int] = {}
        urgency_correlation_id: str | None = None
        if batching.enabled and batching.score_urgency and scorer is not None:
            signalled = [(ri, sid) for (ri, sid) in items if ri.urgency_signals]
            if signalled:
                urgency_correlation_id = str(uuid.uuid4())
                try:
                    with llm_call_context(
                        origin="queue_scorer",
                        purpose="score_urgency",
                        stage="scoring",
                        correlation_id=urgency_correlation_id,
                    ):
                        scores = await scorer.score_urgency_many(
                            [(ri.raw_text, ri.urgency_signals) for ri, _ in signalled],
                            max_batch_size=batching.max_batch_size,
                        )
                    for (ri, _), s in zip(signalled, scores):
                        prescored[id(ri)] = s
                except Exception as e:
                    logger.error("Batch urgency scoring failed: %s", e)
        enqueued = 0
        scored_root_paths: list[str] = []
        for ri, sid in items:
            try:
                job, root_path = await self.pipeline.enqueue(
                    ri.raw_text,
                    ri.source_type,
                    source_id=sid,
                    urgency_signals=ri.urgency_signals,
                    trigger=trigger,
                    urgency_score=prescored.get(id(ri)),
                    source_ref=ri.source_ref,
                    source_url=ri.source_url,
                )
                enqueued += 1
                # Only roots that were part of the batched (signalled) scoring set.
                if (
                    root_path is not None
                    and id(ri) in prescored
                ):
                    scored_root_paths.append(root_path)
            except Exception as e:
                logger.error("Failed to enqueue item %s: %s", sid, e)

        if (
            urgency_correlation_id is not None
            and scored_root_paths
            and getattr(self.stores, "entity_links", None) is not None
        ):
            await self.stores.entity_links.record_by_correlation(
                "llm_call", urgency_correlation_id, scored_root_paths
            )
        return enqueued
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_batched_urgency_lineage.py tests/test_batching.py -v --tb=short`
  Expected: PASS.

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/scheduler.py tests/test_batched_urgency_lineage.py && git commit -m "feat(lineage): batched urgency links scored roots via correlation_id"`

---

### Task 14: Interpret sites stamp the card's item path + record the interaction link

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_interpret_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_interpret_lineage.py`:
```python
"""The free-text interpret_triage_response call stamps the card's item path, and
the resulting InteractionEntry is linked via entity_item_links at that path.

This test drives the small helper extracted in Task 14:
scheduler._interpret_item_path(card) -> str | None resolves the card's item_id to
its path; and _record_interaction_link(entry_id, path) writes the link.
"""

import pytest
from unittest.mock import MagicMock

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.pipeline.scheduler import WorkbenchScheduler

pytestmark = pytest.mark.asyncio


async def test_interpret_item_path_resolves_card_item(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    card = MagicMock()
    card.item_id = root.id
    path = await sched._interpret_item_path(card)
    assert path == root.path

    card_no_item = MagicMock()
    card_no_item.item_id = None
    assert await sched._interpret_item_path(card_no_item) is None


async def test_record_interaction_link_writes_row(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    await sched._record_interaction_link(55, root.path)
    rows = await stores.entity_links.for_entity("interaction", 55)
    assert {r.item_path for r in rows} == {root.path}
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_interpret_lineage.py -v --tb=short`
  Expected: `AttributeError: 'WorkbenchScheduler' object has no attribute '_interpret_item_path'`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py`, add two small helpers on `WorkbenchScheduler`:
```python
    async def _interpret_item_path(self, card) -> str | None:
        """Resolve a card's item_id to its materialized path, or None."""
        item_id = getattr(card, "item_id", None)
        if not item_id:
            return None
        item = await self.stores.items.get_item(item_id)
        return item.path if item else None

    async def _record_interaction_link(self, entry_id: int, path: str | None) -> None:
        """Link an InteractionEntry to the item path it concerns (call-time)."""
        if (
            path
            and entry_id is not None
            and getattr(self.stores, "entity_links", None) is not None
        ):
            await self.stores.entity_links.record("interaction", entry_id, [path])
```

Stamp the card's item path on BOTH free-text `interpret_triage_response` sites (the `awaiting_followup` block ~line 638 and the `sent_cards` free-text fallback ~line 687). For each, resolve the path before the call and stamp it:
```python
                    item_path = await self._interpret_item_path(card)
                    with llm_call_context(
                        origin="aggregate",
                        purpose="interpret_triage_response",
                        stage="aggregate",
                        item_paths=((item_path,) if item_path else ()),
                    ):
                        interpreted = await self.llm.interpret_triage_response(
                            card, text
                        )
                    await self._execute_interpreted_response(interpreted, card)
```

In `_execute_interpreted_response` (the method that builds `InteractionEntry(...)` and calls `self.stores.interactions.append(entry)` at lines ~803-813 and ~845-855), after each `append`, the entry now carries a DB-assigned `entry.id` (the `PgInteractionStore.append` writes the id back onto the entry — verify it mutates `entry.id`). Resolve the card's path and record the link after the append. Add right after each `await self.stores.interactions.append(entry)` inside this method:
```python
                await self.stores.interactions.append(entry)
                _path = await self._interpret_item_path(card)
                await self._record_interaction_link(entry.id, _path)
```
(`_execute_interpreted_response(self, interpreted, card)` has `card` in scope. If `PgInteractionStore.append` does not currently set `entry.id`, change it to `entry.id = row["id"]` after the `RETURNING id` fetch so the link can reference it.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_interpret_lineage.py tests/test_free_text_response.py -v --tb=short`
  Expected: PASS.

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/scheduler.py src/workbench/storage/postgres/interactions.py tests/test_interpret_lineage.py && git commit -m "feat(lineage): interpret stamps card item path + records interaction link"`

---

### Task 15: Message capture at the card send site → persist `Message` + link

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_message_capture_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_message_capture_lineage.py`:
```python
"""When a queued card is sent, the scheduler persists a Message and links it to
the card's item path via entity_item_links (entity_type='message')."""

import pytest
from unittest.mock import MagicMock

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus
from workbench.pipeline.scheduler import WorkbenchScheduler

pytestmark = pytest.mark.asyncio


async def test_capture_card_message_persists_and_links(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores

    msg = await sched._capture_message(
        kind="card",
        direction="outbound",
        bot_message_id="bot-99",
        body="What would you like to do?",
        summary="card for #" + root.path,
        item_path=root.path,
    )
    assert msg.id is not None
    got = await stores.messages.get_by_id(msg.id)
    assert got.bot_message_id == "bot-99"
    links = await stores.entity_links.for_entity("message", msg.id)
    assert {l.item_path for l in links} == {root.path}


async def test_capture_message_without_path_links_nothing(stores):
    sched = WorkbenchScheduler.__new__(WorkbenchScheduler)
    sched.stores = stores
    msg = await sched._capture_message(
        kind="alert", direction="outbound", bot_message_id="b", body="x",
        summary="s", item_path=None,
    )
    assert msg.id is not None
    assert await stores.entity_links.for_entity("message", msg.id) == []
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_message_capture_lineage.py -v --tb=short`
  Expected: `AttributeError: 'WorkbenchScheduler' object has no attribute '_capture_message'`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py`, add `from workbench.domain.messages import Message` to the imports, and add a helper:
```python
    async def _capture_message(
        self,
        *,
        kind: str,
        direction: str,
        bot_message_id: str | None,
        body: str | None,
        summary: str | None,
        item_path: str | None,
    ) -> Message:
        """Persist a durable Message and link it (call-time) to the item path it
        concerns. Returns the saved Message (id assigned). A no-store-configured
        deployment is a safe no-op that still returns an unsaved Message."""
        message = Message(
            kind=kind,
            direction=direction,
            bot_message_id=bot_message_id,
            body=body,
            summary=summary,
        )
        if getattr(self.stores, "messages", None) is None:
            return message
        message = await self.stores.messages.save(message)
        if (
            item_path
            and message.id is not None
            and getattr(self.stores, "entity_links", None) is not None
        ):
            await self.stores.entity_links.record("message", message.id, [item_path])
        return message
```

Wire it into the card send site (the queued-card branch, ~line 705 where `msg_id = await self.messenger.send_card(message)` then sets `card.bot_message_id = msg_id`). After the send and before/after updating the card, capture the message:
```python
        ext_item = self._ext_item_for(card)
        message = self.presenter.render(card, ext_item)
        msg_id = await self.messenger.send_card(message)
        card.status = "sent"
        card.sent_at = datetime.now(timezone.utc)
        card.bot_message_id = msg_id
        card.daily_sequence = sent_today + 1
        await self.stores.triage.update_card(card)

        _card_path = await self._interpret_item_path(card)
        await self._capture_message(
            kind="card",
            direction="outbound",
            bot_message_id=msg_id,
            body=message,
            summary=f"card #{card.id}",
            item_path=_card_path,
        )
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_message_capture_lineage.py -v --tb=short`
  Expected: PASS.

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/scheduler.py tests/test_message_capture_lineage.py && git commit -m "feat(lineage): capture durable Message + message link at card send site"`

---

### Task 16: `GET /api/items/{path}/related` endpoint

**Files:**
- Modify: `src/workbench/api/items.py`
- Test: `tests/test_items_related_api.py`

- [ ] Step 1: Write the failing test

`tests/test_items_related_api.py`:
```python
"""GET /api/items/{path}/related returns entities grouped by type: the UNION of
entity_item_links (joined to its entity tables) and the three FK tables
(triage_card / enrichment_trace / feedback_correction), with counts and a
subtree toggle."""

import pytest
from httpx import AsyncClient, ASGITransport

from workbench.domain import (
    Item, ItemCategory, ItemOrigin, Priority, ItemStatus, TriageCard,
)

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import items as items_api
    app = FastAPI()
    app.include_router(items_api.router)
    app.state.stores = stores
    return app


async def test_related_unions_links_and_fk(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    # An entity_item_links llm_call row.
    await stores.entity_links.record("llm_call", 991, [root.path])
    # A triage_card FK row at the same item.
    card = TriageCard(card_content={"summary": "s"})
    card.item_id = root.id
    await stores.triage.save_card(card)

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(f"/api/items/{root.path}/related")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == root.path
    assert data["counts"].get("llm_call", 0) >= 1
    assert data["counts"].get("triage_card", 0) >= 1
    llm_entries = data["groups"]["llm_call"]
    assert all("entity_type" in e and "id" in e and "label" in e for e in llm_entries)


async def test_related_subtree_toggle(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.EXTRACTED,
        )
    )
    child = await stores.items.allocate_child(
        root,
        Item(
            source_type="t", source_id="r1", summary="c",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        ),
    )
    await stores.entity_links.record("llm_call", 1, [child.path])

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        shallow = (await ac.get(f"/api/items/{root.path}/related")).json()
        deep = (await ac.get(f"/api/items/{root.path}/related?subtree=true")).json()
    assert shallow["counts"].get("llm_call", 0) == 0
    assert deep["counts"].get("llm_call", 0) == 1


async def test_related_resolves_correlation_only_llm_call(stores):
    root = await stores.items.create_root(
        Item(
            source_type="t", source_id="r1", summary="root",
            category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    # Persist an llm_calls row carrying the correlation_id, then a correlation link.
    from datetime import datetime, timezone
    from workbench.domain.llm_calls import LlmCallRecord
    await stores.llm_calls.save_many(
        [LlmCallRecord(started_at=datetime.now(timezone.utc), origin="o", purpose="p",
                       stage="filter", model="m", status="ok", correlation_id="corr-7")]
    )
    await stores.entity_links.record_by_correlation("llm_call", "corr-7", [root.path])

    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        data = (await ac.get(f"/api/items/{root.path}/related")).json()
    entries = data["groups"]["llm_call"]
    # entity_id was NULL on the link row; the endpoint resolved it via the join.
    assert any(e["id"] is not None for e in entries)
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_items_related_api.py -v --tb=short`
  Expected: 404 (route does not exist), so `assert r.status_code == 200` fails.

- [ ] Step 3: Write minimal implementation

In `src/workbench/api/items.py`, add a `/related` route. IMPORTANT: register it BEFORE the existing `@router.get("/items/{path}")` route so `related` is not swallowed by the path param (FastAPI matches in declaration order — add it above `get_item_by_path`). It assembles the UNION of `entity_item_links` (joined for `llm_call` id resolution and labels) and the three FK tables.
```python
_RELATED_CAP = 50

_HREF = {
    "llm_call": lambda e: f"/llm/{e['id']}" if e["id"] is not None else None,
    "interaction": lambda e: f"/interactions/{e['id']}",
    "message": lambda e: f"/messages/{e['id']}",
    "triage_card": lambda e: None,
    "enrichment_trace": lambda e: None,
    "feedback_correction": lambda e: None,
    "plan": lambda e: None,
}


@router.get("/items/{path}/related")
async def item_related(path: str, request: Request, subtree: bool = Query(False)):
    """Entities that touched ``path`` (and descendants when subtree=true),
    grouped by entity_type: UNION of entity_item_links (joined to llm_calls for
    correlation-only id resolution) and the three depth-0 FK tables."""
    stores = request.app.state.stores
    pool = stores.items.pool

    if subtree:
        path_pred = "(eil.item_path = $1 OR eil.item_path LIKE $1 || '.%')"
        fk_pred = "(i.path = $1 OR i.path LIKE $1 || '.%')"
    else:
        path_pred = "eil.item_path = $1"
        fk_pred = "i.path = $1"

    # entity_item_links side. For llm_call rows whose entity_id is NULL
    # (correlation-only), resolve via llm_calls.correlation_id.
    link_rows = await pool.fetch(
        f"""
        SELECT eil.entity_type,
               COALESCE(eil.entity_id, lc.id) AS id,
               eil.item_path,
               eil.created_at,
               lc.purpose AS lc_purpose,
               lc.status  AS lc_status
          FROM entity_item_links eil
          LEFT JOIN llm_calls lc
            ON eil.entity_type = 'llm_call'
           AND eil.entity_id IS NULL
           AND lc.correlation_id = eil.correlation_id
         WHERE {path_pred}
         ORDER BY eil.created_at DESC, eil.id DESC
        """,
        path,
    )

    groups: dict[str, list] = {}

    def _push(entity_type: str, entry: dict) -> None:
        bucket = groups.setdefault(entity_type, [])
        if len(bucket) < _RELATED_CAP:
            href_fn = _HREF.get(entity_type, lambda e: None)
            entry["href"] = href_fn(entry)
            bucket.append(entry)

    for r in link_rows:
        et = r["entity_type"]
        eid = r["id"]
        if et == "llm_call":
            label = f"{r['lc_purpose'] or 'llm_call'} · {r['lc_status'] or '?'}"
        else:
            label = f"{et} #{eid}" if eid is not None else et
        _push(
            et,
            {
                "entity_type": et,
                "id": eid,
                "label": label,
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    # Three FK tables, filtered by item path.
    tc_rows = await pool.fetch(
        f"SELECT tc.id, tc.created_at FROM triage_cards tc "
        f"JOIN items i ON i.id = tc.item_id WHERE {fk_pred} "
        f"ORDER BY tc.created_at DESC",
        path,
    )
    for r in tc_rows:
        _push(
            "triage_card",
            {
                "entity_type": "triage_card",
                "id": r["id"],
                "label": f"card #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    et_rows = await pool.fetch(
        f"SELECT et.id, et.timestamp AS created_at FROM enrichment_trace et "
        f"JOIN items i ON i.id = et.item_id WHERE {fk_pred} "
        f"ORDER BY et.timestamp DESC",
        path,
    )
    for r in et_rows:
        _push(
            "enrichment_trace",
            {
                "entity_type": "enrichment_trace",
                "id": r["id"],
                "label": f"enrichment #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    fc_rows = await pool.fetch(
        f"SELECT fc.id, fc.created_at FROM feedback_corrections fc "
        f"JOIN items i ON i.id = fc.item_id WHERE {fk_pred} "
        f"ORDER BY fc.created_at DESC",
        path,
    )
    for r in fc_rows:
        _push(
            "feedback_correction",
            {
                "entity_type": "feedback_correction",
                "id": r["id"],
                "label": f"feedback #{r['id']}",
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            },
        )

    counts = {et: len(entries) for et, entries in groups.items()}
    return {"path": path, "subtree": subtree, "counts": counts, "groups": groups}
```
(Verify the FK column/table names against the schema: `triage_cards.item_id`, `enrichment_trace.item_id`, `feedback_corrections.item_id`. The enrichment_trace table has `timestamp` (not `created_at`), so the above query selects it AS created_at and orders by timestamp; triage_cards and feedback_corrections have created_at.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_items_related_api.py -v --tb=short`
  Expected: PASS (3 tests). If a FK table/column mismatch surfaces, fix the query column names per the schema and re-run.

- [ ] Step 5: Commit
  `git add src/workbench/api/items.py tests/test_items_related_api.py && git commit -m "feat(lineage): GET /api/items/{path}/related (UNION links + FK tables)"`

---

### Task 17: UI — `useItemRelated` hook

**Files:**
- Modify: `ui/src/hooks/useItems.ts`
- Test: `ui/src/hooks/useItemRelated.test.tsx`

- [ ] Step 1: Write the failing test

`ui/src/hooks/useItemRelated.test.tsx`:
```tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useItemRelated } from './useItems'
import { _resetToken } from '@/lib/api'

const PAYLOAD = {
  path: '123',
  subtree: false,
  counts: { llm_call: 1, triage_card: 1 },
  groups: {
    llm_call: [{ entity_type: 'llm_call', id: 991, label: 'score_relevance · ok', at: '2026-06-18T15:02:11Z', href: '/llm/991' }],
    triage_card: [{ entity_type: 'triage_card', id: 5, label: 'card #5', at: '2026-06-18T15:00:00Z', href: null }],
  },
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/123/related', ({ request }) => {
    const url = new URL(request.url)
    return HttpResponse.json({ ...PAYLOAD, subtree: url.searchParams.get('subtree') === 'true' })
  }),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useItemRelated', () => {
  it('fetches /related and returns grouped entities', async () => {
    const { result } = renderHook(() => useItemRelated('123', false), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.counts.llm_call).toBe(1)
    expect(result.current.data!.groups.llm_call[0].href).toBe('/llm/991')
  })

  it('passes subtree=true', async () => {
    const { result } = renderHook(() => useItemRelated('123', true), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.subtree).toBe(true)
  })
})
```

- [ ] Step 2: Run test to verify it fails
  Run: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run src/hooks/useItemRelated.test.tsx`
  Expected: fails — `useItemRelated` is not exported from `./useItems`.

- [ ] Step 3: Write minimal implementation

Append to `ui/src/hooks/useItems.ts`:
```ts
export interface RelatedEntry {
  entity_type: string
  id: number | null
  label: string
  at: string | null
  href: string | null
}

export interface ItemRelatedData {
  path: string
  subtree: boolean
  counts: Record<string, number>
  groups: Record<string, RelatedEntry[]>
}

export function useItemRelated(path: string, subtree = false) {
  return useQuery({
    queryKey: ['item-related', path, subtree],
    queryFn: () =>
      apiGet<ItemRelatedData>(
        `/api/items/${path}/related${subtree ? '?subtree=true' : ''}`,
      ),
    enabled: !!path,
  })
}
```

- [ ] Step 4: Run test to verify it passes
  Run: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run src/hooks/useItemRelated.test.tsx`
  Expected: PASS (2 tests).

- [ ] Step 5: Commit
  `git add ui/src/hooks/useItems.ts ui/src/hooks/useItemRelated.test.tsx && git commit -m "feat(lineage): useItemRelated react-query hook"`

---

### Task 18: UI — "What touched this" section on `ItemPage`

**Files:**
- Modify: `ui/src/pages/ItemPage.tsx`
- Test: `ui/src/pages/ItemPage.related.test.tsx`

- [ ] Step 1: Write the failing test

`ui/src/pages/ItemPage.related.test.tsx`:
```tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ItemPage } from './ItemPage'
import { _resetToken } from '@/lib/api'

const ITEM = {
  item: { id: 123, path: '123', seq: null, summary: 'root', status: 'extracted' },
  ancestors: [],
  children: [],
}

const RELATED = {
  path: '123',
  subtree: false,
  counts: { llm_call: 1, triage_card: 1 },
  groups: {
    llm_call: [{ entity_type: 'llm_call', id: 991, label: 'score_relevance · ok', at: null, href: '/llm/991' }],
    triage_card: [{ entity_type: 'triage_card', id: 5, label: 'card #5', at: null, href: null }],
  },
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/123', () => HttpResponse.json(ITEM)),
  http.get('/api/items/123/related', ({ request }) => {
    const url = new URL(request.url)
    return HttpResponse.json({ ...RELATED, subtree: url.searchParams.get('subtree') === 'true' })
  }),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/items/123']}>
        <Routes>
          <Route path="/items/*" element={<ItemPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemPage What touched this', () => {
  it('renders the related section grouped by type with a link for llm_call', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('What touched this')).toBeTruthy())
    const link = await screen.findByRole('link', { name: /score_relevance/ })
    expect(link.getAttribute('href')).toContain('/llm/991')
    // triage_card has no href -> plain text, not a link.
    expect(screen.getByText('card #5')).toBeTruthy()
  })

  it('include-descendants toggle re-fetches with subtree=true', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('What touched this')).toBeTruthy())
    const toggle = screen.getByLabelText('include descendants')
    fireEvent.click(toggle)
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true))
  })
})
```

- [ ] Step 2: Run test to verify it fails
  Run: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run src/pages/ItemPage.related.test.tsx`
  Expected: fails — `Unable to find an element with the text: What touched this`.

- [ ] Step 3: Write minimal implementation

In `ui/src/pages/ItemPage.tsx`, import the new hook and add a section. Update the import line:
```tsx
import { useItem, useItemRelated, type ItemChild } from '@/hooks/useItems'
```
Add a `RelatedSection` component above `ItemPage`:
```tsx
function RelatedSection({ path }: { path: string }) {
  const [subtree, setSubtree] = useState(false)
  const q = useItemRelated(path, subtree)
  const groups = q.data?.groups ?? {}
  const counts = q.data?.counts ?? {}
  const types = Object.keys(groups)
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          What touched this
        </h2>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            aria-label="include descendants"
            checked={subtree}
            onChange={(e) => setSubtree(e.target.checked)}
          />
          include descendants
        </label>
      </div>
      {q.isPending && <Skeleton className="h-6 w-full" />}
      {types.length === 0 && !q.isPending && (
        <div className="text-sm text-muted-foreground">Nothing linked yet.</div>
      )}
      {types.map((t) => (
        <div key={t} className="space-y-1">
          <div className="text-xs font-semibold">
            {t} ({counts[t] ?? groups[t].length})
          </div>
          {groups[t].map((e) => (
            <div key={`${t}-${e.id}`} className="flex items-center gap-2 text-sm">
              {e.href ? (
                <a href={e.href} className="text-primary hover:underline">
                  {e.label}
                </a>
              ) : (
                <span>{e.label}</span>
              )}
            </div>
          ))}
        </div>
      ))}
    </section>
  )
}
```
And render it inside `ItemPage`'s returned JSX, just after the Children `</section>`:
```tsx
      </section>
      <RelatedSection path={item.path ?? path} />
    </div>
  )
}
```

- [ ] Step 4: Run test to verify it passes
  Run: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run src/pages/ItemPage.related.test.tsx`
  Expected: PASS (2 tests).

- [ ] Step 5: Commit
  `git add ui/src/pages/ItemPage.tsx ui/src/pages/ItemPage.related.test.tsx && git commit -m "feat(lineage): ItemPage 'What touched this' section + subtree toggle"`

---

### Task 19: Retention cascade — wire `entity_links` into `run_retention_cleanup` pruners

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_retention_lineage.py`

- [ ] Step 1: Write the failing test

`tests/test_retention_lineage.py`:
```python
"""run_retention_cleanup passes stores.entity_links into the llm_calls pruners and
sweeps messages so message link rows do not dangle."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from workbench.pipeline.scheduler import run_retention_cleanup
from workbench.config.models import RetentionConfig

pytestmark = pytest.mark.asyncio


def _stores():
    s = MagicMock()
    s.items.delete_older_than = AsyncMock(return_value=0)
    s.triage.delete_older_than = AsyncMock(return_value=0)
    s.enrichment.delete_older_than = AsyncMock(return_value=0)
    s.ingestion_queue.delete_dead_letters_older_than = AsyncMock(return_value=0)
    s.ingestion_runs.delete_older_than = AsyncMock(return_value=0)
    s.llm_calls.delete_older_than = AsyncMock(return_value=0)
    s.llm_calls.prune_to_max_rows = AsyncMock(return_value=0)
    s.entity_links = MagicMock()
    s.messages = MagicMock()
    s.messages.delete_older_than = AsyncMock(return_value=3)
    return s


async def test_llm_calls_pruners_receive_entity_links():
    s = _stores()
    config = RetentionConfig(llm_calls_max_rows=1000)
    await run_retention_cleanup(s, config)
    _, kwargs = s.llm_calls.delete_older_than.call_args
    assert kwargs.get("entity_links") is s.entity_links
    _, kwargs2 = s.llm_calls.prune_to_max_rows.call_args
    assert kwargs2.get("entity_links") is s.entity_links


async def test_messages_swept():
    s = _stores()
    config = RetentionConfig()
    result = await run_retention_cleanup(s, config)
    s.messages.delete_older_than.assert_awaited_once()
    assert result.get("messages") == 3
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_retention_lineage.py -v --tb=short`
  Expected: `delete_older_than` called without `entity_links` kwarg; `messages` not swept (`AssertionError`).

- [ ] Step 3: Write minimal implementation

In `src/workbench/pipeline/scheduler.py::run_retention_cleanup`, update the llm_calls block to pass `entity_links` and add a messages sweep. Replace the existing llm_calls block:
```python
    # LLM usage tracking retention (Task 10) + lineage cascade.
    entity_links = getattr(stores, "entity_links", None)
    if getattr(stores, "llm_calls", None) is not None:
        results["llm_calls"] = await stores.llm_calls.delete_older_than(
            config.llm_calls_days, entity_links=entity_links
        )
        if config.llm_calls_max_rows is not None:
            results["llm_calls_pruned"] = await stores.llm_calls.prune_to_max_rows(
                config.llm_calls_max_rows, entity_links=entity_links
            )

    # Durable messages retention. Item-side links cascade with the item; the
    # message entity side has no DB FK, but pruning here keeps the table bounded.
    if getattr(stores, "messages", None) is not None:
        results["messages"] = await stores.messages.delete_older_than(
            config.llm_calls_days
        )
```
(Uses `config.llm_calls_days` as the messages window to avoid a new config field; if a `messages_days` field is desired it can be added to `RetentionConfig` later. YAGNI: reuse the existing window for now.)

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_retention_lineage.py tests/test_llm_calls_retention.py -v --tb=short`
  Expected: PASS. (`test_llm_calls_retention.py` uses `assert_awaited_once_with(28)` — that asserts positional-only; the new `entity_links` kwarg makes it `assert_awaited_once_with(28, entity_links=...)`. Update those two existing assertions in `test_llm_calls_retention.py` to `assert_awaited_once_with(28, entity_links=s.entity_links)` and `assert_awaited_once_with(1000, entity_links=s.entity_links)`, and add `s.entity_links = MagicMock()` to that file's `_stores()` helper.)

- [ ] Step 5: Commit
  `git add src/workbench/pipeline/scheduler.py tests/test_retention_lineage.py tests/test_llm_calls_retention.py && git commit -m "feat(lineage): retention pruners cascade-unlink llm_calls + sweep messages"`

---

### Task 20: Plan linkage stub at the future creation site

**Files:**
- Modify: `src/workbench/domain/plans.py`
- Test: `tests/test_plan_link_stub.py`

This task documents the one-line linkage contract for Plans (which have no caller/API yet, per Out of Scope) so a future Plan creation site links in one call, without wiring an end-to-end path now.

- [ ] Step 1: Write the failing test

`tests/test_plan_link_stub.py`:
```python
"""Plan carries an item_paths stub field so the future creation site can call
record('plan', plan.id, plan.item_paths) in one line (no end-to-end wiring yet)."""

from workbench.domain.plans import Plan


def test_plan_has_item_paths_stub_default_empty():
    p = Plan(title="t")
    assert p.item_paths == []


def test_plan_accepts_item_paths():
    p = Plan(title="t", item_paths=["123", "123.1"])
    assert p.item_paths == ["123", "123.1"]
```

- [ ] Step 2: Run test to verify it fails
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_plan_link_stub.py -v --tb=short`
  Expected: `pydantic` error / `AttributeError` — `Plan` has no `item_paths`.

- [ ] Step 3: Write minimal implementation

In `src/workbench/domain/plans.py`, add the stub field to `Plan`:
```python
class Plan(BaseModel):
    id: int | None = None
    title: str
    status: str = "draft"
    content: str = ""
    sources: list[str] = Field(default_factory=list)
    # Lineage stub: the item path(s) this plan was built from. The future Plan
    # creation site links in one line: record("plan", plan.id, plan.item_paths).
    # Not persisted yet (no plans schema column); carried in-memory for the
    # linkage contract (ADR 0063 §Out of Scope).
    item_paths: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] Step 4: Run test to verify it passes
  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_plan_link_stub.py -v --tb=short`
  Expected: PASS (2 tests). (If `PgPlanStore.save_plan` does a column-exact INSERT and now chokes on the extra field, ensure it serializes only known columns — `item_paths` is in-memory only; verify `test_*plan*` store tests still pass in Task 21.)

- [ ] Step 5: Commit
  `git add src/workbench/domain/plans.py tests/test_plan_link_stub.py && git commit -m "feat(lineage): Plan.item_paths linkage stub for the future creation site"`

---

### Task 21: Full-suite verification

**Files:** none (verification only)

- [ ] Step 1: Re-apply schema and run the full backend suite
  Run: `$HOME/.venv/workbench/bin/python -m alembic upgrade head && $HOME/.venv/workbench/bin/python -m pytest tests/ -q`
  Expected: PASS (no failures, no errors). Pay attention to pre-existing tests that touched the changed surfaces: `test_llm_calls_store.py`, `test_llm_calls_retention.py`, `test_llm_writer.py`, `test_llm_capture*.py`, `test_batching.py`, `test_free_text_response.py`, and any `test_*plan*` / `test_process*` / API tests that call `pipeline.enqueue`. Fix any caller that still expects the old `enqueue` bare-job return or the old `score_and_decide` 3-tuple.

- [ ] Step 2: Run the full UI suite
  Run: `cd ui && PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH ./node_modules/.bin/vitest run`
  Expected: PASS.

- [ ] Step 3: Build the UI
  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run build`
  Expected: build succeeds (no TS errors).

- [ ] Step 4: Confirm migration round-trips down and back up
  Run: `$HOME/.venv/workbench/bin/python -m alembic downgrade 014 && $HOME/.venv/workbench/bin/python -m alembic upgrade head`
  Expected: clean downgrade (drops `entity_item_links`, `messages`, `llm_calls.correlation_id`) and re-upgrade.

- [ ] Step 5: Commit (only if any fixups were needed in steps 1-4)
  `git add -A && git commit -m "test(lineage): full backend + UI suite green; migration round-trips"`
