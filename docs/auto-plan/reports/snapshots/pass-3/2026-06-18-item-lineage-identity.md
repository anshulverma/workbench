# Item Lineage & Stable Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give every `Item` a unique, stable, hierarchical identity (`#123`, `#123.1`, `#123.1.2`) assigned at ingestion and traceable through the LLM pre-persist stages, extraction, and the action queue, with navigable lineage.

**Architecture:** Keep the integer surrogate PK and add a materialized-path pair (`seq SMALLINT NULL`, `path TEXT NOT NULL`) plus two new `ItemStatus` values (`INGESTED`, `EXTRACTED`). A migration adds the columns, constraints (`UNIQUE(path)`, `UNIQUE(parent_item_id, seq)`, partial `UNIQUE(source_type, source_id) WHERE parent_item_id IS NULL`), and indexes, with a depth-iterative backfill. All path/seq logic is confined to two new store methods (`create_root`, `allocate_child`) so the denormalized `path` never leaks to call sites. The pipeline engine births a root at `enqueue`, creates depth-1 children at extraction, and the scheduler creates depth-2+ action children; `LLMCallContext` carries the path id so `LlmCallRecord.items` records real lineage references. A `GET /api/items/{path}` endpoint returns `{item, ancestors[], children[]}`, and a new `/items/:path` UI route renders one `ItemPage` (breadcrumb + lazy children) linked from every surface that shows an item or action.

**Tech Stack:** Python 3.12, FastAPI, asyncpg/Postgres, Alembic; React 19 + TypeScript, Vite, TanStack Query, Vitest + Testing Library + MSW.

**Test commands:**
- Backend (all): `$HOME/.venv/workbench/bin/python -m pytest tests/ -v --tb=short`  (baseline ~643 tests)
- Backend (single test): `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_allocate_child_paths -v --tb=short`
- Backend requires a live Postgres at `postgres://workbench:workbench@localhost:5432/workbench` with the schema applied via `$HOME/.venv/workbench/bin/python -m alembic upgrade head` (the `stores`/`pg_pool` fixtures in `tests/conftest.py` only TRUNCATE; they do **not** create the schema). Re-run `alembic upgrade head` after writing the migration so the test DB has `seq`/`path`.
- UI (all): `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run test`  (baseline ~498 tests)
- UI (single file): `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/pages/ItemPage.test.tsx`
- UI build/typecheck: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run build`

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/workbench/domain/enums.py` | Modify | Add `INGESTED`, `EXTRACTED` to `ItemStatus`. |
| `src/workbench/domain/items.py` | Modify | Add `seq: int \| None` and `path: str \| None` to `Item`. |
| `src/workbench/migrations/versions/014_item_lineage.py` | Create | Add `seq`/`path` columns, constraints, indexes; backfill non-empty DBs. |
| `src/workbench/storage/base.py` | Modify | Add `create_root` (Task 4), `allocate_child` (Task 5), `get_by_path`/`get_ancestors`/`get_children` (Task 6) `@abstractmethod`s to `ItemStore` ABC — each added in the same task as its `PgItemStore` impl so the concrete class stays instantiable. |
| `src/workbench/storage/postgres/items.py` | Modify | Implement the five new methods on `PgItemStore`; carry `seq`/`path` in `save_item`/`_row_to_item`; add `AND parent_item_id IS NULL` to `get_item_by_source_id` so it resolves the root, not a child (root and children share `(source_type, source_id)`). |
| `src/workbench/pipeline/engine.py` | Modify | Create root at `enqueue` (`INGESTED`); depth-1 children via `allocate_child` at extraction; mark root `EXTRACTED`. |
| `src/workbench/pipeline/scheduler.py` | Modify | Action children via `allocate_child` on the relevant parent. |
| `src/workbench/providers/llm/context.py` | Modify | Add optional `item_paths` to `LLMCallContext` + `llm_call_context`. |
| `src/workbench/runtime/app.py` | Modify | Prefer `context.item_paths` for `LlmCallRecord.items` when present. |
| `src/workbench/api/items.py` | Modify | Add `GET /api/items/{path}` returning `{item, ancestors[], children[]}`. |
| `ui/src/hooks/useItems.ts` | Modify | Add `useItem(path)` hook; add `seq`/`path` to the `Item` TS type. |
| `ui/src/pages/ItemPage.tsx` | Create | Breadcrumb + body + lazy-expand children; serves both root and action. |
| `ui/src/App.tsx` | Modify | Add `/items/:path` route. |
| `ui/src/pages/ActionItems.tsx` | Modify | Link rows to `/items/{path}`. |
| `ui/src/pages/TriageDetail.tsx` | Modify | Link the card's item path to `/items/{path}`. |
| `ui/src/pages/Ingestion.tsx` | Modify | Link funnel item rows to `/items/{path}`. |
| `ui/src/pages/Search.tsx` | Modify | Link search result rows to `/items/{path}`. |
| `ui/src/pages/SystemStatus.tsx` | Modify | Make LLM Infra subcall `items` clickable `→ /items/{path}`. |

---

## Task 1: Domain — add `INGESTED`/`EXTRACTED` statuses and `seq`/`path` to `Item`

**Files:**
- Modify: `src/workbench/domain/enums.py`
- Modify: `src/workbench/domain/items.py`
- Test: `tests/test_domain_surface.py`

- [ ] **Step 1: Write the failing test**  Append to `tests/test_domain_surface.py`:
```python
def test_item_status_has_lineage_stages():
    from workbench.domain import ItemStatus

    assert ItemStatus.INGESTED.value == "ingested"
    assert ItemStatus.EXTRACTED.value == "extracted"


def test_item_carries_seq_and_path():
    from workbench.domain import Item, ItemCategory, ItemOrigin, Priority

    root = Item(
        source_type="diff",
        source_id="D1",
        summary="s",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.MANUAL,
        priority=Priority.P2,
    )
    # defaults: unset until persisted / allocated
    assert root.seq is None
    assert root.path is None

    child = Item(
        source_type="diff",
        source_id="D1",
        summary="c",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.TRIAGED,
        priority=Priority.P2,
        seq=1,
        path="123.1",
        parent_item_id=123,
    )
    assert child.seq == 1
    assert child.path == "123.1"
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_domain_surface.py::test_item_status_has_lineage_stages tests/test_domain_surface.py::test_item_carries_seq_and_path -v --tb=short`  Expected: first test fails with `AttributeError: INGESTED` (no such `ItemStatus` member). Second test: `Item` is a Pydantic v2 `BaseModel` with **no** `extra="forbid"`, so `Item(..., seq=1, path="...")` silently ignores the unknown kwargs and does **not** raise on construction; the test instead fails at `assert root.seq is None` with `AttributeError: 'Item' object has no attribute 'seq'` (the field does not exist on the model yet).

- [ ] **Step 3: Write minimal implementation**  In `src/workbench/domain/enums.py`, add the two members to `ItemStatus` (after `DROPPED`):
```python
    # Lineage lifecycle (D2/D3): a root is born INGESTED at enqueue and moves to
    # EXTRACTED once its depth-1 children exist. Verdict statuses live on the
    # children, not the root.
    INGESTED = "ingested"
    EXTRACTED = "extracted"
```
  In `src/workbench/domain/items.py`, add two fields to `Item` (right after `parent_item_id`):
```python
    # Materialized-path lineage (D1). `seq` is the 1-based index among siblings
    # (NULL for roots); `path` is the full lineage string ("123", "123.1").
    # Both are assigned by the store allocation seam (create_root/allocate_child)
    # and are immutable after insert (D4) — None on an unpersisted Item.
    seq: int | None = None
    path: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_domain_surface.py::test_item_status_has_lineage_stages tests/test_domain_surface.py::test_item_carries_seq_and_path -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(domain): add INGESTED/EXTRACTED statuses and seq/path to Item"`

---

## Task 2: Migration 014 — lineage columns, constraints, indexes, backfill

**Files:**
- Create: `src/workbench/migrations/versions/014_item_lineage.py`
- Test: `tests/test_migration_014.py`

> NOTE: The repo's actual latest revision is `013` (`013_llm_calls.py`), not `011`/`012` as the source spec text says. This migration is therefore `014` with `down_revision = "013"`. (Resolution of a spec/repo drift; see report.)

- [ ] **Step 1: Write the failing test**  Create `tests/test_migration_014.py`:
```python
import importlib


def test_migration_014_revision_chain():
    m = importlib.import_module("workbench.migrations.versions.014_item_lineage")
    assert m.revision == "014" and m.down_revision == "013"
    assert callable(m.upgrade) and callable(m.downgrade)
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_migration_014.py -v --tb=short`  Expected: `ModuleNotFoundError: No module named 'workbench.migrations.versions.014_item_lineage'`

- [ ] **Step 3: Write minimal implementation**  Create `src/workbench/migrations/versions/014_item_lineage.py`:
```python
"""Item lineage & stable identity: materialized path on ``items``.

Adds ``seq SMALLINT NULL`` and ``path TEXT`` (set NOT NULL after backfill),
the lineage constraints, and the path indexes (D1/D4 of the design):

  - UNIQUE(path)
  - UNIQUE(parent_item_id, seq)             -- concurrent-sibling race backstop
  - partial UNIQUE(source_type, source_id) WHERE parent_item_id IS NULL
      -- never two roots for one source thing (closes dedup gap #4)
  - B-tree on path with text_pattern_ops    -- indexed LIKE '123.%' subtree scans
  - B-tree on parent_item_id

Backfill handles a non-empty DB (no-op when empty): roots get path = id::text;
children get seq = row_number() per parent and path = parent.path || '.' || seq,
applied iteratively by depth via a recursive CTE so multi-level chains resolve.

Revision ID: 014
Revises: 013
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("seq", sa.SmallInteger, nullable=True))
    op.add_column("items", sa.Column("path", sa.Text, nullable=True))

    # Backfill (no-op on an empty table). Roots first, then a recursive CTE
    # walks depth by depth so a child's path is built from its (already set)
    # parent's path.
    op.execute("UPDATE items SET path = id::text WHERE parent_item_id IS NULL")
    op.execute(
        """
        WITH RECURSIVE seqd AS (
            SELECT id, parent_item_id,
                   row_number() OVER (
                       PARTITION BY parent_item_id ORDER BY id
                   ) AS seq
              FROM items
             WHERE parent_item_id IS NOT NULL
        ),
        tree AS (
            SELECT i.id, i.parent_item_id, NULL::smallint AS seq, i.id::text AS path
              FROM items i
             WHERE i.parent_item_id IS NULL
            UNION ALL
            SELECT s.id, s.parent_item_id, s.seq::smallint,
                   t.path || '.' || s.seq AS path
              FROM seqd s
              JOIN tree t ON s.parent_item_id = t.id
        )
        UPDATE items i
           SET seq = tr.seq, path = tr.path
          FROM tree tr
         WHERE i.id = tr.id
           AND tr.parent_item_id IS NOT NULL
        """
    )

    op.alter_column("items", "path", nullable=False)

    op.create_unique_constraint("uq_items_path", "items", ["path"])
    op.create_unique_constraint(
        "uq_items_parent_seq", "items", ["parent_item_id", "seq"]
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_items_root_source "
        "ON items (source_type, source_id) WHERE parent_item_id IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_items_path_pattern "
        "ON items (path text_pattern_ops)"
    )
    op.create_index("idx_items_parent_item_id", "items", ["parent_item_id"])


def downgrade() -> None:
    op.drop_index("idx_items_parent_item_id", table_name="items")
    op.execute("DROP INDEX IF EXISTS idx_items_path_pattern")
    op.execute("DROP INDEX IF EXISTS uq_items_root_source")
    op.drop_constraint("uq_items_parent_seq", "items", type_="unique")
    op.drop_constraint("uq_items_path", "items", type_="unique")
    op.drop_column("items", "path")
    op.drop_column("items", "seq")
```

- [ ] **Step 4: Run test to verify it passes, then apply to the test DB**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_migration_014.py -v --tb=short`  Expected: PASS. Then apply the schema so later tasks' DB tests have the columns: `$HOME/.venv/workbench/bin/python -m alembic upgrade head`  Expected: `Running upgrade 013 -> 014`.

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(migration): 014 item lineage columns, constraints, indexes, backfill"`

---

## Task 3: Migration 014 — round-trip backfill on a seeded 3-level DB

**Files:**
- Test: `tests/test_migration_014.py`

> This task verifies the backfill SQL against a live DB by replaying it on seeded rows (the migration's upgrade already ran in Task 2; here we assert correctness on representative data inserted with NULL path then re-backfilled by the same SQL).

- [ ] **Step 1: Write the failing test**  Append to `tests/test_migration_014.py`:
```python
import pytest

_BACKFILL = """
WITH RECURSIVE seqd AS (
    SELECT id, parent_item_id,
           row_number() OVER (PARTITION BY parent_item_id ORDER BY id) AS seq
      FROM items WHERE parent_item_id IS NOT NULL
),
tree AS (
    SELECT i.id, i.parent_item_id, NULL::smallint AS seq, i.id::text AS path
      FROM items i WHERE i.parent_item_id IS NULL
    UNION ALL
    SELECT s.id, s.parent_item_id, s.seq::smallint, t.path || '.' || s.seq AS path
      FROM seqd s JOIN tree t ON s.parent_item_id = t.id
)
UPDATE items i SET seq = tr.seq, path = tr.path
  FROM tree tr WHERE i.id = tr.id AND tr.parent_item_id IS NOT NULL
"""


async def _insert(pool, *, parent=None, source_id="x"):
    row = await pool.fetchrow(
        """INSERT INTO items
           (source_type, source_id, summary, category, origin, priority,
            status, raw_data, created_at, updated_at, parent_item_id)
           VALUES ('diff', $1, 's', 'action_item', 'manual', 'P2',
                   'active', '{}'::jsonb, NOW(), NOW(), $2)
           RETURNING id""",
        source_id,
        parent,
    )
    return row["id"]


@pytest.mark.asyncio
async def test_migration_014_backfills_three_levels(pg_pool):
    root = await _insert(pg_pool, source_id="D-root")
    child = await _insert(pg_pool, parent=root, source_id="c1")
    grandchild = await _insert(pg_pool, parent=child, source_id="g1")

    # Simulate a pre-014 state: clear the freshly-set lineage, then backfill.
    await pg_pool.execute("UPDATE items SET seq = NULL, path = NULL")
    await pg_pool.execute("UPDATE items SET path = id::text WHERE parent_item_id IS NULL")
    await pg_pool.execute(_BACKFILL)

    paths = {
        r["id"]: r["path"]
        for r in await pg_pool.fetch("SELECT id, path FROM items")
    }
    assert paths[root] == str(root)
    assert paths[child] == f"{root}.1"
    assert paths[grandchild] == f"{root}.1.1"
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_migration_014.py::test_migration_014_backfills_three_levels -v --tb=short`  Expected: PASS only if Task 2's `alembic upgrade head` already added the `path` column; if the columns are missing it fails with `asyncpg.exceptions.UndefinedColumnError: column "path" of relation "items" does not exist` — run `alembic upgrade head` (Task 2 Step 4) and retry. (The test asserts correct multi-level backfill; it is the meaningful red→green for the backfill SQL.)

- [ ] **Step 3: Write minimal implementation**  No code change — the backfill SQL in `014_item_lineage.py` already implements this. (If the assertion fails on path values, fix the recursive CTE in the migration to match the asserted `root` / `root.1` / `root.1.1` shape.)

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_migration_014.py -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "test(migration): 014 round-trips 3-level lineage backfill"`

---

## Task 4: Store — `create_root` (insert, RETURNING id, set path = str(id))

**Files:**
- Modify: `src/workbench/storage/base.py`
- Modify: `src/workbench/storage/postgres/items.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**  Append to `tests/test_storage.py`:
```python
@pytest.mark.asyncio
async def test_create_root_sets_path_to_id(stores):
    item = Item(
        source_type="diff",
        source_id="D-root-1",
        summary="root",
        category=ItemCategory.ACTION_ITEM,
        origin=ItemOrigin.MANUAL,
        priority="P2",
        status=ItemStatus.INGESTED,
    )
    saved = await stores.items.create_root(item)
    assert saved.id is not None
    assert saved.seq is None
    assert saved.path == str(saved.id)
    assert saved.parent_item_id is None

    fetched = await stores.items.get_item(saved.id)
    assert fetched.path == str(saved.id)
    assert fetched.status == ItemStatus.INGESTED
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_create_root_sets_path_to_id -v --tb=short`  Expected: `AttributeError: 'PgItemStore' object has no attribute 'create_root'`

- [ ] **Step 3: Write minimal implementation**  **ABC discipline (CRITICAL):** an `@abstractmethod` on `ItemStore` makes `PgItemStore` non-instantiable until that exact method is implemented on the concrete class, which would break the `stores` fixture (`tests/conftest.py` → `create_postgres_stores()` → `PgItemStore()`) with `TypeError: Can't instantiate abstract class PgItemStore with abstract methods ...`. So each task adds an `@abstractmethod` **only together with** its `PgItemStore` implementation. This task adds **only** `create_root` (ABC + impl); `allocate_child` arrives in Task 5 and the three navigation methods in Task 6.

  In `src/workbench/storage/base.py`, add **only** this one abstract method to the `ItemStore` ABC (after `save_item`):
```python
    @abstractmethod
    async def create_root(self, item: Item) -> Item:
        """Insert a depth-0 item and set path = str(id) (D1/D3)."""
        ...
```
  In `src/workbench/storage/postgres/items.py`, update `save_item`'s INSERT to also write `seq`/`path` (so existing call sites still work — children created via plain `save_item` keep NULL lineage until migrated to `allocate_child`). The existing INSERT (items.py ~47-82) has a contiguous `$1..$22` over 22 columns ending at `verdict_confidence`. Make exactly these edits, no renumbering of `$1..$22`:
  - In the column list, after `verdict_confidence)` append `, seq, path` → `... verdict_confidence, seq, path)`.
  - In the VALUES list, after `$22)` append `, $23, $24` → `... $20, $21, $22, $23, $24)`.
  - In the positional args, after the `item.verdict_confidence,` line append two lines: `item.seq,` and `item.path,`.

  Then add the `create_root` method to `PgItemStore` (this is the impl that pairs with the ABC declaration above):
```python
    async def create_root(self, item: Item) -> Item:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO items
                       (source_type, source_id, summary, category, origin,
                        priority, status, raw_data, created_at, updated_at,
                        parent_item_id, action_source, action_category,
                        snoozed_until, completed_at, tags, llm_summary,
                        enriched_context, funnel_log, verdict_action,
                        verdict_priority, verdict_confidence, seq, path)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,
                               NULL,$11,$12,$13,$14,$15::jsonb,$16,
                               $17::jsonb,$18::jsonb,$19,$20,$21,NULL,'')
                       RETURNING id""",
                    item.source_type, item.source_id, item.summary,
                    item.category.value, item.origin.value, item.priority.value,
                    item.status.value, json.dumps(item.raw_data),
                    item.created_at, item.updated_at, item.action_source,
                    item.action_category, item.snoozed_until, item.completed_at,
                    json.dumps(item.tags), item.llm_summary,
                    json.dumps(item.enriched_context), json.dumps(item.funnel_log),
                    item.verdict_action, item.verdict_priority,
                    item.verdict_confidence,
                )
                item.id = row["id"]
                item.seq = None
                item.path = str(item.id)
                await conn.execute(
                    "UPDATE items SET path = $1 WHERE id = $2", item.path, item.id
                )
        return item
```
  Also add `seq=row.get("seq")` and `path=row.get("path")` to the `Item(...)` construction inside `_row_to_item`.

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_create_root_sets_path_to_id -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(store): create_root allocates path=str(id) for root items"`

---

## Task 5: Store — `allocate_child` (seq = MAX+1, path = parent.path.seq, retry)

**Files:**
- Modify: `src/workbench/storage/postgres/items.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**  Append to `tests/test_storage.py`:
```python
@pytest.mark.asyncio
async def test_allocate_child_paths(stores):
    root = await stores.items.create_root(
        Item(source_type="diff", source_id="D-ac-1", summary="r",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
             priority="P2", status=ItemStatus.INGESTED)
    )
    c1 = await stores.items.allocate_child(
        root,
        Item(source_type="diff", source_id="D-ac-1", summary="c1",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
             priority="P2", status=ItemStatus.ACTIVE),
    )
    c2 = await stores.items.allocate_child(
        root,
        Item(source_type="diff", source_id="D-ac-1", summary="c2",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
             priority="P2", status=ItemStatus.ACTIVE),
    )
    assert c1.seq == 1 and c1.path == f"{root.id}.1"
    assert c2.seq == 2 and c2.path == f"{root.id}.2"
    assert c1.parent_item_id == root.id

    gc = await stores.items.allocate_child(
        c1,
        Item(source_type="diff", source_id="D-ac-1", summary="gc",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
             priority="P2", status=ItemStatus.ACTIVE),
    )
    assert gc.seq == 1 and gc.path == f"{root.id}.1.1"


@pytest.mark.asyncio
async def test_allocate_child_concurrent_no_collision(stores):
    # Determinism: allocate_child takes pg_advisory_xact_lock(parent.id) as the
    # first statement in its txn, serializing all 8 siblings on the same parent
    # so seq allocation cannot collide even though the pool max_size (~5) is
    # smaller than the fan-out. The result must be exactly paths .1 .. .8 with 8
    # distinct seqs, every time.
    import asyncio as _asyncio

    root = await stores.items.create_root(
        Item(source_type="diff", source_id="D-cc-1", summary="r",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
             priority="P2", status=ItemStatus.INGESTED)
    )

    def _mk(n):
        return Item(source_type="diff", source_id="D-cc-1", summary=f"c{n}",
                    category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
                    priority="P2", status=ItemStatus.ACTIVE)

    results = await _asyncio.gather(
        *(stores.items.allocate_child(root, _mk(n)) for n in range(8))
    )
    paths = sorted(r.path for r in results)
    assert paths == sorted(f"{root.id}.{i}" for i in range(1, 9))
    assert len({r.seq for r in results}) == 8


@pytest.mark.asyncio
async def test_deletion_leaves_gap_without_renumber(stores):
    root = await stores.items.create_root(
        Item(source_type="diff", source_id="D-gap-1", summary="r",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
             priority="P2", status=ItemStatus.INGESTED)
    )
    c1 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-gap-1", summary="c1",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    c2 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-gap-1", summary="c2",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    await stores.items.pool.execute("DELETE FROM items WHERE id = $1", c1.id)
    c3 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-gap-1", summary="c3",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    assert c2.path == f"{root.id}.2"
    assert c3.path == f"{root.id}.3"  # gap left by c1, never reused


@pytest.mark.asyncio
async def test_duplicate_root_for_source_blocked(stores):
    import asyncpg

    await stores.items.create_root(
        Item(source_type="diff", source_id="D-dup-1", summary="r",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
             priority="P2", status=ItemStatus.INGESTED)
    )
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await stores.items.create_root(
            Item(source_type="diff", source_id="D-dup-1", summary="r2",
                 category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
                 priority="P2", status=ItemStatus.INGESTED)
        )
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_allocate_child_paths tests/test_storage.py::test_allocate_child_concurrent_no_collision tests/test_storage.py::test_deletion_leaves_gap_without_renumber tests/test_storage.py::test_duplicate_root_for_source_blocked -v --tb=short`  Expected: `AttributeError: 'PgItemStore' object has no attribute 'allocate_child'` (the duplicate-root test passes already since `create_root` + the partial unique index exist after Task 2/4).

- [ ] **Step 3: Write minimal implementation**  First add the `allocate_child` `@abstractmethod` to the `ItemStore` ABC in `src/workbench/storage/base.py` (after the `create_root` abstractmethod added in Task 4) — paired with the concrete impl below so `PgItemStore` stays instantiable:
```python
    @abstractmethod
    async def allocate_child(self, parent: Item, child: Item) -> Item:
        """Insert a child: seq = MAX(seq)+1 over siblings, path = parent.path.seq."""
        ...
```
  **Concurrency mechanism (chosen): a transaction-scoped Postgres advisory lock keyed on the parent id (`pg_advisory_xact_lock(parent.id)`), taken as the first statement in the txn.** This serializes all concurrent `allocate_child` calls for the *same* parent so the `COALESCE(MAX(seq),0)+1` read-then-insert is race-free even when the connection pool is smaller than the number of concurrent siblings (the lock is held on the connection, released automatically at txn commit/rollback; it does not require holding a row lock or pre-existing parent row state). The `UNIQUE(parent_item_id, seq)` constraint + retry loop remain as a defense-in-depth backstop, and the retry bound is raised to `range(20)` (comfortably above any realistic concurrent sibling fan-out) so a transient conflict never exhausts retries. Add to `PgItemStore` in `src/workbench/storage/postgres/items.py`:
```python
    async def allocate_child(self, parent: Item, child: Item) -> Item:
        # seq = MAX(seq)+1 over siblings, computed and inserted in one txn. A
        # txn-scoped advisory lock on parent.id serializes concurrent siblings so
        # the read-then-insert is race-free regardless of pool size; the
        # UNIQUE(parent_item_id, seq) constraint + retry are a backstop (D1
        # allocation seam, D4 append-only gaps).
        import asyncpg

        for _ in range(20):
            try:
                async with self.pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(
                            "SELECT pg_advisory_xact_lock($1)", parent.id
                        )
                        seq_row = await conn.fetchrow(
                            "SELECT COALESCE(MAX(seq), 0) + 1 AS seq "
                            "FROM items WHERE parent_item_id = $1",
                            parent.id,
                        )
                        seq = int(seq_row["seq"])
                        path = f"{parent.path}.{seq}"
                        row = await conn.fetchrow(
                            """INSERT INTO items
                               (source_type, source_id, summary, category, origin,
                                priority, status, raw_data, created_at, updated_at,
                                parent_item_id, action_source, action_category,
                                snoozed_until, completed_at, tags, llm_summary,
                                enriched_context, funnel_log, verdict_action,
                                verdict_priority, verdict_confidence, seq, path)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,
                                       $11,$12,$13,$14,$15,$16::jsonb,$17,
                                       $18::jsonb,$19::jsonb,$20,$21,$22,$23,$24)
                               RETURNING id""",
                            child.source_type, child.source_id, child.summary,
                            child.category.value, child.origin.value,
                            child.priority.value, child.status.value,
                            json.dumps(child.raw_data), child.created_at,
                            child.updated_at, parent.id, child.action_source,
                            child.action_category, child.snoozed_until,
                            child.completed_at, json.dumps(child.tags),
                            child.llm_summary, json.dumps(child.enriched_context),
                            json.dumps(child.funnel_log), child.verdict_action,
                            child.verdict_priority, child.verdict_confidence,
                            seq, path,
                        )
                child.id = row["id"]
                child.seq = seq
                child.path = path
                child.parent_item_id = parent.id
                return child
            except asyncpg.exceptions.UniqueViolationError:
                continue
        raise RuntimeError(
            f"allocate_child: exhausted retries allocating seq under {parent.id}"
        )
```

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_allocate_child_paths tests/test_storage.py::test_allocate_child_concurrent_no_collision tests/test_storage.py::test_deletion_leaves_gap_without_renumber tests/test_storage.py::test_duplicate_root_for_source_blocked -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(store): allocate_child assigns seq/path with unique-violation retry"`

---

## Task 6: Store — `get_by_path`, `get_ancestors`, `get_children`

**Files:**
- Modify: `src/workbench/storage/postgres/items.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**  Append to `tests/test_storage.py`:
```python
@pytest.mark.asyncio
async def test_get_by_path_and_ancestors_and_children(stores):
    root = await stores.items.create_root(
        Item(source_type="diff", source_id="D-nav-1", summary="root",
             category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
             priority="P2", status=ItemStatus.INGESTED)
    )
    c1 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-nav-1", summary="c1",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    c2 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-nav-1", summary="c2",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    gc = await stores.items.allocate_child(c1, Item(
        source_type="diff", source_id="D-nav-1", summary="gc",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))

    # get_by_path
    by_path = await stores.items.get_by_path(gc.path)
    assert by_path is not None and by_path.id == gc.id
    assert await stores.items.get_by_path("999.9.9") is None

    # ancestors: root-first, excludes self
    anc = await stores.items.get_ancestors(gc)
    assert [a.path for a in anc] == [root.path, c1.path]

    # children with has_children flags
    kids = await stores.items.get_children(root.id)
    by_id = {item.id: has for item, has in kids}
    assert by_id[c1.id] is True   # c1 has gc
    assert by_id[c2.id] is False  # c2 has none
    assert sorted(item.seq for item, _ in kids) == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_get_by_path_and_ancestors_and_children -v --tb=short`  Expected: `AttributeError: 'PgItemStore' object has no attribute 'get_by_path'`

- [ ] **Step 3: Write minimal implementation**  First add the three navigation `@abstractmethod`s to the `ItemStore` ABC in `src/workbench/storage/base.py` (after the `allocate_child` abstractmethod added in Task 5) — paired with the concrete impls below so `PgItemStore` stays instantiable (this is the last task that adds abstract methods; after it all five are declared and implemented):
```python
    @abstractmethod
    async def get_by_path(self, path: str) -> Item | None: ...
    @abstractmethod
    async def get_ancestors(self, item: Item) -> list[Item]:
        """Root-first chain of ancestors of ``item`` (excludes item itself)."""
        ...
    @abstractmethod
    async def get_children(self, parent_id: int) -> list[tuple[Item, bool]]:
        """Direct children of ``parent_id``, each with a has_children flag."""
        ...
```
  Then add the matching impls to `PgItemStore`:
```python
    async def get_by_path(self, path: str) -> Item | None:
        row = await self.pool.fetchrow("SELECT * FROM items WHERE path = $1", path)
        return self._row_to_item(row) if row else None

    async def get_ancestors(self, item: Item) -> list[Item]:
        # Ancestors are the strict path prefixes: "123.1.2" -> ["123", "123.1"].
        if not item.path or "." not in item.path:
            return []
        segments = item.path.split(".")
        prefixes = [
            ".".join(segments[: i + 1]) for i in range(len(segments) - 1)
        ]
        rows = await self.pool.fetch(
            "SELECT * FROM items WHERE path = ANY($1::text[]) ORDER BY length(path), path",
            prefixes,
        )
        return [self._row_to_item(r) for r in rows]

    async def get_children(self, parent_id: int) -> list[tuple[Item, bool]]:
        rows = await self.pool.fetch(
            """SELECT c.*,
                      EXISTS (SELECT 1 FROM items g WHERE g.parent_item_id = c.id)
                          AS has_children
                 FROM items c
                WHERE c.parent_item_id = $1
                ORDER BY c.seq""",
            parent_id,
        )
        return [(self._row_to_item(r), bool(r["has_children"])) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_storage.py::test_get_by_path_and_ancestors_and_children -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(store): get_by_path/get_ancestors/get_children navigation"`

---

## Task 7: Pipeline engine — birth a root at `enqueue` (INGESTED)

**Files:**
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**  Append to `tests/test_pipeline.py`:
```python
@pytest.mark.asyncio
async def test_enqueue_births_root_item(stores, mock_llm):
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher

    engine = PipelineEngine(
        stores=stores,
        memory=NoopMemoryLayer(),
        llm=mock_llm,
        enricher=StubEnricher(),
    )
    await engine.enqueue(
        raw_text="some diff text",
        source_type="diff",
        source_id="D-birth-1",
        trigger=JobTrigger.MANUAL,
    )
    root = await stores.items.get_item_by_source_id("diff", "D-birth-1")
    assert root is not None
    assert root.status == ItemStatus.INGESTED
    assert root.path == str(root.id)
    assert root.parent_item_id is None
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_pipeline.py::test_enqueue_births_root_item -v --tb=short`  Expected: `AssertionError: assert None is not None` (no root item is created at enqueue today).

- [ ] **Step 3: Write minimal implementation**  In `src/workbench/pipeline/engine.py`, inside `enqueue`, after `await self.stores.jobs.save_job(job)` (the QUEUED job, ~line 167) and before urgency scoring, create the root. **Do NOT add any field to `IngestionQueueEntry`** — the queue entry does not carry `root_item_id`. The root is born here and is later *re-resolved* at extraction time (Task 8) via `get_item_by_source_id(source_type, source_id)`, which is backed by the partial `UNIQUE(source_type, source_id) WHERE parent_item_id IS NULL` key (Migration 014), so the root id never needs to travel through the queue. (Note: `get_item_by_source_id` filters out `archived`/`done` statuses but `INGESTED`/`EXTRACTED` pass, so the re-resolve sees the root.) Create the root:
```python
        # Birth the root Item now (D3): the autoincrement assigns #123
        # immediately, so the id is stable for the whole journey (incl. the
        # LLM pre-persist window). Status INGESTED -> EXTRACTED once children
        # exist. source_id may be None for ad-hoc enqueues; only born when set.
        # No id is stashed on the queue entry — extraction re-resolves the root
        # by (source_type, source_id) via get_item_by_source_id.
        root_item = None
        if source_id:
            # Root carries the source snapshot so the scheduler change-detector
            # diffs the root on re-poll. VERIFIED shape invariant: the ONLY
            # change-detection consumer is scheduler._parse_raw, which reads only
            # raw_data["raw_text"] and json.loads-es it; every in-scope adapter
            # (diff/Phabricator, meta_tasks, google_docs, gmail, github) sets
            # RawItem.raw_text to the JSON-encoded source record, so this single
            # {"raw_text", "source_type", "id"} shape is correct for ALL source
            # types. No adapter reads any other raw_data key for change-detection.
            root_item = await self.stores.items.create_root(
                Item(
                    source_type=source_type,
                    source_id=source_id,
                    summary=(raw_text[:200] if raw_text else ""),
                    category=ItemCategory.INFORMATIONAL,
                    origin=ItemOrigin.AUTO_INCLUDED,
                    priority=Priority.PENDING,
                    status=ItemStatus.INGESTED,
                    raw_data={"raw_text": raw_text, "source_type": source_type, "id": source_id},
                )
            )
```
  Add `ItemCategory` to the `from workbench.domain import (...)` block at the top of the file. Place this block right after the QUEUED `save_job` call so the dedup early-return above it (the `is_processed` branch) is unaffected.

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_pipeline.py::test_enqueue_births_root_item -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(pipeline): birth root Item at enqueue with INGESTED status"`

---

## Task 8: Pipeline engine — depth-1 children at extraction; root → EXTRACTED

**Files:**
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_pipeline.py`

> Extraction currently saves each extracted item as a fresh top-level `Item` via `save_item` (engine.py ~296-388). Reparent them under the ingestion root using `allocate_child`, and move the root to `EXTRACTED` once children exist.

- [ ] **Step 1: Write the failing test**  Append to `tests/test_pipeline.py`:
```python
@pytest.mark.asyncio
async def test_extraction_creates_depth1_children_under_root(stores, mock_llm):
    from workbench.providers.memory.noop import NoopMemoryLayer
    from workbench.providers.enrichment.stub import StubEnricher

    engine = PipelineEngine(
        stores=stores,
        memory=NoopMemoryLayer(),
        llm=mock_llm,
        enricher=StubEnricher(),
    )
    job = await engine.enqueue(
        raw_text="diff text", source_type="diff", source_id="D-ext-1",
        trigger=JobTrigger.MANUAL,
    )
    root = await stores.items.get_item_by_source_id("diff", "D-ext-1")

    raw = RawItem(id="D-ext-1", source_type="diff", source_label="D-ext-1",
                  raw_text="diff text")
    await engine.process_raw_item(raw, job.id)

    children = await stores.items.get_children(root.id)
    assert len(children) == 1
    child, _ = children[0]
    assert child.path == f"{root.id}.1"
    assert child.parent_item_id == root.id

    refreshed_root = await stores.items.get_item(root.id)
    assert refreshed_root.status == ItemStatus.EXTRACTED


@pytest.mark.asyncio
async def test_get_item_by_source_id_resolves_root_not_child(stores):
    # After a root + child share (source_type, source_id), the source-id
    # resolver must return the root (parent_item_id IS NULL), not the child.
    root = await stores.items.create_root(Item(
        source_type="diff", source_id="D-res-1", summary="root",
        category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
        priority="P2", status=ItemStatus.INGESTED,
        raw_data={"raw_text": "{}", "source_type": "diff", "id": "D-res-1"}))
    await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-res-1", summary="child",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    resolved = await stores.items.get_item_by_source_id("diff", "D-res-1")
    assert resolved is not None
    assert resolved.id == root.id
    assert resolved.parent_item_id is None
```
  **Also add to `tests/test_change_monitoring_routing.py`:**
```python
@pytest.mark.asyncio
async def test_seen_root_and_children_not_archived_on_complete_poll(sched, stores):
    # Gap-1 regression: get_active_by_source returns roots AND children; a root
    # whose stable source_id is present in a complete poll's seen_ids must NOT be
    # archived, and neither must its children (they share the same stable
    # source_id, set via the worker reconstructing raw_item.id = entry.source_id).
    from workbench.domain import ItemCategory, ItemOrigin, ItemStatus
    root = await stores.items.create_root(Item(
        source_type="diff", source_id="D7", summary="root",
        category=ItemCategory.INFORMATIONAL, origin=ItemOrigin.AUTO_INCLUDED,
        priority="P2", status=ItemStatus.EXTRACTED,
        raw_data={"raw_text": '{"status":"needs_review"}',
                  "source_type": "diff", "id": "D7"}))
    child = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D7", summary="extracted",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    # Complete poll that still contains D7 (raw id "D7_222" -> stable_id "D7").
    await sched._route_poll_results(
        "src", _Adapter(complete=True), _Detector(_result()),
        [_raw("D7_222")], JobTrigger.POLL,
    )
    assert (await stores.items.get_item(root.id)).status == ItemStatus.EXTRACTED
    assert (await stores.items.get_item(child.id)).status == ItemStatus.ACTIVE
```
  This test reuses the existing `sched`, `stores`, `_Adapter`, `_Detector`, `_result`, `_raw`, `JobTrigger` helpers already present in `tests/test_change_monitoring_routing.py`; if a helper name differs, mirror the file's existing helpers.

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_pipeline.py::test_extraction_creates_depth1_children_under_root tests/test_change_monitoring_routing.py::test_seen_root_and_children_not_archived_on_complete_poll -v --tb=short`  Expected: `AssertionError: assert 0 == 1` (extracted items are saved as roots, not children). The routing test may fail with helper import errors if the test file structure differs — adjust the helper names (`_Adapter`, `_Detector`, `_result`, `_raw`) to match `tests/test_change_monitoring_routing.py`'s existing fixture factories.

- [ ] **Step 3: Write minimal implementation**  
  1. **First, fix `get_item_by_source_id` to resolve the root only:** In `src/workbench/storage/postgres/items.py`, change `get_item_by_source_id` to add `AND parent_item_id IS NULL` to its WHERE clause so it resolves the root only — otherwise after children exist the existing `ORDER BY created_at DESC LIMIT 1` returns a child and both the extraction re-resolve and the scheduler change-detection loop bind the wrong row.
  2. In `engine.py`, in `process_raw_item`, resolve the ingestion root once before the per-item loop and pass it down:
```python
        root = await self.stores.items.get_item_by_source_id(
            raw_item.source_type, raw_item.id
        )
```
  Then change the loop call to `await self._process_extracted_item(ext_item, job, precomputed=score, root=root)`, and after the loop, if `root is not None and items:` move it to EXTRACTED:
```python
            if root is not None and items:
                await self.stores.items.update_item(
                    root.id, ItemUpdate(status=ItemStatus.EXTRACTED)
                )
```
  Add `ItemUpdate` to the domain import block.
  2. Change `_process_extracted_item` signature to accept `root: Item | None = None`. In all three branches (`auto_include`, `auto_drop`, `else`/triage), replace `await self.stores.items.save_item(item)` with a root-aware allocation:
```python
            if root is not None:
                item = await self.stores.items.allocate_child(root, item)
            else:
                await self.stores.items.save_item(item)
```
  Build each `item` exactly as today (same fields), but do **not** set `parent_item_id` on the constructed `Item` — `allocate_child` sets it. The triage branch already references `item.id` after save for `card.item_id`; that still holds since `allocate_child` sets `item.id`. KEEP children's `source_id = ext_item.raw_item.id` exactly as today: at extraction `raw_item.id` is the **stable** source id (the worker reconstructs `RawItem.id = entry.source_id`, which the scheduler set to `adapter.stable_id(...)`), so root and children share the identical stable `source_id`. This is what keeps both archival-safe under `_detect_disappeared`/`get_active_by_source` (the new `test_seen_root_and_children_not_archived_on_complete_poll` guards it) — do NOT switch children to the volatile `RawItem.id`.

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_pipeline.py::test_extraction_creates_depth1_children_under_root tests/test_change_monitoring_routing.py::test_seen_root_and_children_not_archived_on_complete_poll -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(pipeline): nest extracted items under root, mark root EXTRACTED"`

---

## Task 9: Scheduler — triage-response actions via `allocate_child`

**Files:**
- Modify: `src/workbench/pipeline/scheduler.py`
- Test: `tests/test_free_text_response.py`

> The free-text branch creates user-todo action items with `parent_item_id=card.item_id` via `save_item` (scheduler.py ~859-873). Switch to `allocate_child` so the action gets a proper depth-2+ path under its parent item.

- [ ] **Step 1: Write the failing test**  Append a new test to `tests/test_free_text_response.py` (mirror the existing fixtures in that file for `scheduler`/`stores`; if the file builds the scheduler inline, reuse that helper). Minimal shape:
```python
@pytest.mark.asyncio
async def test_user_todo_action_is_allocated_as_child(stores, scheduler_with_card):
    # scheduler_with_card: a scheduler whose card.item_id points at a persisted
    # depth-1 item (created via create_root + allocate_child). See helper below.
    scheduler, card, parent_item = scheduler_with_card
    from workbench.domain import InterpretedResponse, UserTodo

    interpreted = InterpretedResponse(
        explanation="add a follow-up",
        system_actions=[],
        user_todos=[UserTodo(summary="ping reviewer", action_category="communication")],
    )
    await scheduler._execute_interpreted_response(interpreted, card)

    children = await stores.items.get_children(parent_item.id)
    assert len(children) == 1
    action, _ = children[0]
    assert action.summary == "ping reviewer"
    assert action.path == f"{parent_item.path}.1"
    assert action.parent_item_id == parent_item.id
    assert action.action_source == "triage_response"
```
  If `tests/test_free_text_response.py` lacks a `scheduler_with_card` fixture, add one that: `create_root` a root, `allocate_child` a depth-1 `parent_item`, save a `TriageCard` with `item_id=parent_item.id`, and construct the scheduler exactly as the file's other tests do. Keep `InterpretedResponse`/`UserTodo` imports matching `workbench.domain`.

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_free_text_response.py::test_user_todo_action_is_allocated_as_child -v --tb=short`  Expected: `AssertionError` on `action.path` (the action is saved via `save_item` with NULL path), or `assert 0 == 1` because the child has no `seq`/`path` and `get_children` orders by `seq`.

- [ ] **Step 3: Write minimal implementation**  In `scheduler.py`, in `_execute_interpreted_response`, replace the `user_todos` loop body. Resolve the parent once, then allocate each todo as a child:
```python
        parent_item = (
            await self.stores.items.get_item(card.item_id)
            if card.item_id
            else None
        )
        for todo in interpreted.user_todos:
            new_item = Item(
                source_type=card.card_content.get("source_type", "unknown"),
                source_id=str(card.id),
                summary=todo.summary,
                category=ItemCategory.ACTION_ITEM,
                origin=ItemOrigin.TRIAGED,
                priority=Priority.P2,
                status=ItemStatus.ACTIVE,
                action_source="triage_response",
                action_category=todo.action_category,
            )
            if parent_item is not None:
                await self.stores.items.allocate_child(parent_item, new_item)
            else:
                await self.stores.items.save_item(new_item)
```
  (Drop the explicit `parent_item_id=card.item_id` kwarg — `allocate_child` sets it.)

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_free_text_response.py::test_user_todo_action_is_allocated_as_child -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(scheduler): allocate triage-response actions as lineage children"`

---

## Task 10: LLM context — carry path ids into `LLMCallContext`; record them as `items`

**Files:**
- Modify: `src/workbench/providers/llm/context.py`
- Modify: `src/workbench/runtime/app.py`
- Modify: `src/workbench/pipeline/engine.py`
- Test: `tests/test_llm_context.py`

> Today `LlmCallRecord.items` is derived from `subcalls[].item` (free-text). Add an optional `item_paths` to `LLMCallContext` so call sites can stamp real path ids, and prefer it in `app.py` when building the record.

- [ ] **Step 1: Write the failing test**  Append to `tests/test_llm_context.py`:
```python
def test_llm_call_context_carries_item_paths():
    from workbench.providers.llm.context import (
        llm_call_context,
        current_llm_call_context,
    )

    with llm_call_context(
        origin="filter", purpose="score_relevance", stage="filter",
        item_paths=["123.1", "123.2"],
    ):
        ctx = current_llm_call_context()
        assert ctx.item_paths == ("123.1", "123.2")

    # default is empty tuple, and existing 3-arg call sites still work
    with llm_call_context(origin="o", purpose="p", stage="filter"):
        assert current_llm_call_context().item_paths == ()
```

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_llm_context.py::test_llm_call_context_carries_item_paths -v --tb=short`  Expected: `TypeError: llm_call_context() got an unexpected keyword argument 'item_paths'`

- [ ] **Step 3: Write minimal implementation**  In `src/workbench/providers/llm/context.py`:
  - Add `item_paths: tuple[str, ...] = ()` to the `LLMCallContext` dataclass (after `stage`).
  - Change `llm_call_context` signature to `def llm_call_context(*, origin: str, purpose: str, stage: str, item_paths: tuple[str, ...] | list[str] = ()):` and build `LLMCallContext(origin=origin, purpose=purpose, stage=stage, item_paths=tuple(item_paths))`.
  In `src/workbench/runtime/app.py`, in the `LlmCallRecord(...)` construction, change the `items=` argument to prefer the stamped paths:
```python
        items=(
            list(rec.context.item_paths)
            if rec.context and rec.context.item_paths
            else [s["item"] for s in (rec.subcalls or [])]
        ),
```
  In `src/workbench/pipeline/engine.py`, stamp paths where the root/children are known. In `process_raw_item`, the batched relevance call (`with llm_call_context(origin="filter", purpose="score_relevance", stage="filter"):`) gains the root path:
```python
                with llm_call_context(
                    origin="filter", purpose="score_relevance", stage="filter",
                    item_paths=((root.path,) if root else ()),
                ):
```

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_llm_context.py::test_llm_call_context_carries_item_paths -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(llm): stamp item path ids into LLMCallContext and LlmCallRecord.items"`

---

## Task 11: API — `GET /api/items/{path}` returning `{item, ancestors, children}`

**Files:**
- Modify: `src/workbench/api/items.py`
- Test: `tests/test_api.py`

> `{path}` (e.g. `123.1.2`) is a single path segment with dots; it does not conflict with the int `PATCH/DELETE /items/{item_id}` routes (different methods) nor with `/items/search` (FastAPI matches the static `/items/search` first). Register the new GET route **after** `/items/search` in the file.

- [ ] **Step 1: Write the failing test**  Append to `tests/test_api.py` (use the app/client fixture this file already uses; if it uses `httpx.AsyncClient` against the FastAPI app with `stores` injected, mirror that). Minimal shape:
```python
@pytest.mark.asyncio
async def test_get_item_by_path(api_client, stores):
    from workbench.domain import Item, ItemCategory, ItemOrigin, ItemStatus

    root = await stores.items.create_root(Item(
        source_type="diff", source_id="D-api-1", summary="root",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.MANUAL,
        priority="P2", status=ItemStatus.INGESTED))
    c1 = await stores.items.allocate_child(root, Item(
        source_type="diff", source_id="D-api-1", summary="c1",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))
    gc = await stores.items.allocate_child(c1, Item(
        source_type="diff", source_id="D-api-1", summary="gc",
        category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.TRIAGED,
        priority="P2", status=ItemStatus.ACTIVE))

    resp = await api_client.get(f"/api/items/{c1.path}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["item"]["path"] == c1.path
    assert [a["path"] for a in body["ancestors"]] == [root.path]
    assert len(body["children"]) == 1
    assert body["children"][0]["path"] == gc.path
    assert body["children"][0]["has_children"] is False

    missing = await api_client.get("/api/items/999.9")
    assert missing.status_code == 404
```
  If `tests/test_api.py` does not already expose an `api_client`/app fixture, reuse whatever client fixture the existing tests in that file use (search the file for `AsyncClient`/`TestClient`); do not invent a new one.

- [ ] **Step 2: Run test to verify it fails**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_api.py::test_get_item_by_path -v --tb=short`  Expected: `404` for `/api/items/{c1.path}` (route not yet defined) → `assert 404 == 200`.

- [ ] **Step 3: Write minimal implementation**  In `src/workbench/api/items.py`, add after the `search_items` route and before `update_item`:
```python
@router.get("/items/{path}")
async def get_item_by_path(path: str, request: Request):
    stores = request.app.state.stores
    item = await stores.items.get_by_path(path)
    if not item:
        raise HTTPException(404, "Item not found")
    ancestors = await stores.items.get_ancestors(item)
    children = await stores.items.get_children(item.id)
    return {
        "item": item.model_dump(mode="json"),
        "ancestors": [
            {"id": a.id, "path": a.path, "summary": a.summary, "status": a.status}
            for a in ancestors
        ],
        "children": [
            {
                "id": c.id,
                "path": c.path,
                "seq": c.seq,
                "summary": c.summary,
                "status": c.status,
                "priority": c.priority,
                "has_children": has,
            }
            for c, has in children
        ],
    }
```

- [ ] **Step 4: Run test to verify it passes**  Run: `$HOME/.venv/workbench/bin/python -m pytest tests/test_api.py::test_get_item_by_path -v --tb=short`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(api): GET /api/items/{path} with ancestors and lazy children"`

---

## Task 12: UI — `useItem(path)` hook + `seq`/`path` on the `Item` type

**Files:**
- Modify: `ui/src/hooks/useItems.ts`
- Test: `ui/src/hooks/useItem.test.tsx`

- [ ] **Step 1: Write the failing test**  Create `ui/src/hooks/useItem.test.tsx`:
```tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useItem } from './useItems'
import { _resetToken } from '@/lib/api'

const PAYLOAD = {
  item: { id: 1, path: '1', seq: null, summary: 'root', status: 'extracted' },
  ancestors: [],
  children: [
    { id: 2, path: '1.1', seq: 1, summary: 'c1', status: 'active', priority: 'P2', has_children: true },
  ],
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(PAYLOAD)),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useItem', () => {
  it('fetches /api/items/:path and returns item + children', async () => {
    const { result } = renderHook(() => useItem('1'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.item.path).toBe('1')
    expect(result.current.data!.children[0].path).toBe('1.1')
    expect(result.current.data!.children[0].has_children).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/hooks/useItem.test.tsx`  Expected: fails to import — `useItem` is not exported from `./useItems`.

- [ ] **Step 3: Write minimal implementation**  In `ui/src/hooks/useItems.ts`:
  - Add `seq?: number | null` and `path?: string` to the `Item` interface.
  - Add types + hook:
```ts
export interface ItemChild {
  id: number
  path: string
  seq: number | null
  summary: string
  status: string
  priority: string
  has_children: boolean
}

export interface ItemAncestor {
  id: number
  path: string
  summary: string
  status: string
}

export interface ItemPageData {
  item: Item
  ancestors: ItemAncestor[]
  children: ItemChild[]
}

export function useItem(path: string) {
  return useQuery({
    queryKey: ['item', path],
    queryFn: () => apiGet<ItemPageData>(`/api/items/${path}`),
    enabled: !!path,
  })
}
```

- [ ] **Step 4: Run test to verify it passes**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/hooks/useItem.test.tsx`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(ui): useItem(path) hook and seq/path on Item type"`

---

## Task 13: UI — `ItemPage` (breadcrumb + lazy children) + `/items/:path` route

**Files:**
- Create: `ui/src/pages/ItemPage.tsx`
- Modify: `ui/src/App.tsx`
- Test: `ui/src/pages/ItemPage.test.tsx`

> One component serves root and action; the only difference is the breadcrumb (root `#123`; action `#123 / #123.1 / #123.1.2`, each segment a link). Children render collapsed; a chevron lazy-loads the next level via the same endpoint. React Router `:path` with dots needs a splat — use the route `path="/items/*"` and read `params['*']` so `1.1.2` is captured whole.

- [ ] **Step 1: Write the failing test**  Create `ui/src/pages/ItemPage.test.tsx`:
```tsx
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ItemPage } from './ItemPage'
import { _resetToken } from '@/lib/api'

const ROOT = {
  item: { id: 1, path: '1', seq: null, summary: 'root diff', status: 'extracted' },
  ancestors: [],
  children: [
    { id: 2, path: '1.1', seq: 1, summary: 'extracted A', status: 'active', priority: 'P2', has_children: true },
    { id: 3, path: '1.2', seq: 2, summary: 'extracted B', status: 'dropped', priority: 'P3', has_children: false },
  ],
}
const ACTION = {
  item: { id: 4, path: '1.1.1', seq: 1, summary: 'ping reviewer', status: 'active' },
  ancestors: [
    { id: 1, path: '1', summary: 'root diff', status: 'extracted' },
    { id: 2, path: '1.1', summary: 'extracted A', status: 'active' },
  ],
  children: [],
}
const CHILD11 = {
  item: { id: 2, path: '1.1', seq: 1, summary: 'extracted A', status: 'active' },
  ancestors: [{ id: 1, path: '1', summary: 'root diff', status: 'extracted' }],
  children: [
    { id: 4, path: '1.1.1', seq: 1, summary: 'ping reviewer', status: 'active', priority: 'P2', has_children: false },
  ],
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(ROOT)),
  http.get('/api/items/1.1', () => HttpResponse.json(CHILD11)),
  http.get('/api/items/1.1.1', () => HttpResponse.json(ACTION)),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(ROOT)),
  http.get('/api/items/1.1', () => HttpResponse.json(CHILD11)),
  http.get('/api/items/1.1.1', () => HttpResponse.json(ACTION)),
); _resetToken() })
afterAll(() => server.close())

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/items/${path}`]}>
        <Routes>
          <Route path="/items/*" element={<ItemPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemPage', () => {
  it('renders a single-segment breadcrumb for a root', async () => {
    renderAt('1')
    expect(await screen.findByText('root diff')).toBeInTheDocument()
    const crumb = screen.getByTestId('breadcrumb')
    expect(crumb).toHaveTextContent('#1')
    expect(crumb).not.toHaveTextContent('/')
  })

  it('renders a linked multi-segment breadcrumb for an action', async () => {
    renderAt('1.1.1')
    expect(await screen.findByText('ping reviewer')).toBeInTheDocument()
    const crumb = screen.getByTestId('breadcrumb')
    expect(crumb).toHaveTextContent('#1')
    expect(crumb).toHaveTextContent('#1.1')
    expect(crumb).toHaveTextContent('#1.1.1')
    expect(screen.getByRole('link', { name: '#1.1' })).toHaveAttribute('href', '/items/1.1')
  })

  it('lists children collapsed and lazy-loads the next level on expand', async () => {
    renderAt('1')
    expect(await screen.findByText('extracted A')).toBeInTheDocument()
    expect(screen.queryByText('ping reviewer')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('expand-1.1'))
    expect(await screen.findByText('ping reviewer')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/pages/ItemPage.test.tsx`  Expected: import error — `ItemPage` does not exist.

- [ ] **Step 3: Write minimal implementation**  Create `ui/src/pages/ItemPage.tsx`:
```tsx
// Item / Action page (#/items/:path). One component for both: the breadcrumb is
// the only difference (root -> "#123"; action -> "#123 / #123.1 / ..." each a
// link). Children render collapsed; a chevron lazy-loads the next level via the
// same /api/items/:path endpoint (one query per expanded child).
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { useItem, type ItemChild } from '@/hooks/useItems'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

function Breadcrumb({ path }: { path: string }) {
  const segs = path.split('.')
  return (
    <nav data-testid="breadcrumb" className="flex flex-wrap items-center gap-1 text-sm">
      {segs.map((_, i) => {
        const p = segs.slice(0, i + 1).join('.')
        const last = i === segs.length - 1
        return (
          <span key={p} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground">/</span>}
            {last ? (
              <span className="font-mono font-semibold">#{p}</span>
            ) : (
              <Link to={`/items/${p}`} className="font-mono text-primary hover:underline">
                #{p}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}

function ChildRow({ child }: { child: ItemChild }) {
  const [open, setOpen] = useState(false)
  const sub = useItem(open ? child.path : '')
  return (
    <div className="rounded border border-border bg-card">
      <div className="flex items-center gap-2 p-2">
        {child.has_children ? (
          <button
            data-testid={`expand-${child.path}`}
            aria-label={`Expand ${child.path}`}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        ) : (
          <span className="inline-block size-4" />
        )}
        <Link to={`/items/${child.path}`} className="font-mono text-xs text-primary hover:underline">
          #{child.path}
        </Link>
        <span className="min-w-0 flex-1 truncate text-sm">{child.summary}</span>
        <Badge variant="outline">{child.priority}</Badge>
        <Badge variant="secondary">{child.status}</Badge>
      </div>
      {open && (
        <div className="ml-6 space-y-1 border-l border-border pl-2 pb-2">
          {sub.isPending && <Skeleton className="h-6 w-full" />}
          {sub.data?.children.map((c) => <ChildRow key={c.path} child={c} />)}
        </div>
      )}
    </div>
  )
}

export function ItemPage() {
  const params = useParams()
  const path = params['*'] ?? ''
  const q = useItem(path)

  if (q.isPending) {
    return (
      <div data-testid="item-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (q.isError) {
    const err = q.error as ApiError
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load item: {err.message}
      </div>
    )
  }

  const { item, children } = q.data
  return (
    <div className="space-y-4">
      <Breadcrumb path={item.path ?? path} />
      <h1 className="text-lg font-semibold">{item.summary}</h1>
      <div className="text-sm text-muted-foreground">
        {item.source_type} · {item.status}
      </div>
      <section className="space-y-2">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Children ({children.length})
        </h2>
        <div className="space-y-1">
          {children.map((c) => <ChildRow key={c.path} child={c} />)}
        </div>
      </section>
    </div>
  )
}
```
  In `ui/src/App.tsx`, import it and add a route (place near the other item routes):
```tsx
import { ItemPage } from '@/pages/ItemPage'
```
```tsx
          <Route path="/items/*" element={<ItemPage />} />
```

- [ ] **Step 4: Run test to verify it passes**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/pages/ItemPage.test.tsx`  Expected: PASS

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(ui): ItemPage with breadcrumb and lazy-expand children at /items/*"`

---

## Task 14: UI — wire path links into ActionItems, TriageDetail, Ingestion, Search, LLM Infra

**Files:**
- Modify: `ui/src/pages/ActionItems.tsx`
- Modify: `ui/src/pages/TriageDetail.tsx`
- Modify: `ui/src/pages/Ingestion.tsx`
- Modify: `ui/src/pages/Search.tsx`
- Modify: `ui/src/pages/SystemStatus.tsx`
- Modify (as needed): `ui/src/hooks/useActions.ts` (add `path` to the `Action` type if not present)
- Test: `ui/src/pages/ActionItems.test.tsx` (extend), `ui/src/pages/Search.test.tsx` (extend), `ui/src/pages/SystemStatus.test.tsx` (extend)

> Each surface that shows an item/action gets a clickable `#path → /items/{path}` link. The spec names five surfaces: `ActionItems`, `Triage`/`TriageDetail`, `Ingestion` funnel, `Search` results, and the LLM Infra `items` column (`SystemStatus`). This task accounts for **every** one of them — three are tested with presence-gated assertions, two are explicitly deferred with a payload-shape reason:
>
> | Surface | Payload carries a path? | Treatment |
> |---|---|---|
> | `ActionItems` | `Action.path` added in this task's impl (backend `Item.path` is serialized) | **Tested** — render link iff `action.path` present |
> | `Search` | `path` added to `/api/items/search` SELECT + result type in this task | **Tested** — render link iff `r.path` present |
> | `SystemStatus` (LLM Infra `items`) | `LLMSubCall.item` becomes a real path id after Task 10 (`LlmCallRecord.items` stamped from `context.item_paths`) | **Tested** — render link iff `sc.item` matches `/^\d+(\.\d+)*$/` |
> | `Ingestion` funnel | `ActivityItem` (`useStats.ts`) has `id`/`status`/`source_type`/`summary`/`created_at` only — **no `path`** | **Deferred (reasoned):** the `/api/stats/activity` payload does not include `path`; wiring a link would require a backend mapping change out of scope here. Render the link only behind an `item.path` presence gate (no-op today), so the surface lights up automatically once the activity payload carries `path`. No test (the fixture has no path to assert). |
> | `TriageDetail` | `TriageCard` (`useTriage.ts`) has `item_id?` but **no `item_path`/`path`** | **Deferred (reasoned):** the card payload carries `item_id` (an int FK) but not the lineage `path`; rendering a path link would need the card endpoint to also resolve+include the item's `path`, which is out of scope. Gate on `c.card_content.item_path` (or `c.item_path`) presence so it renders iff a future payload supplies it. No test. |
>
> Net: ActionItems + Search + SystemStatus are demonstrably wired (with tests); Ingestion + TriageDetail carry presence-gated link code that is a verified no-op given today's payloads, with the reason recorded above. For surfaces whose API response lacks `path`, render the link only when `path` is present, so partial rollout is safe.

- [ ] **Step 1: Write the failing test**  In `ui/src/pages/ActionItems.test.tsx`, add a test asserting an action row renders a link to its path. Find that file's existing action fixture and add `path: '1.1.1'` to one action object, then:
```tsx
  it('links an action to its item lineage page', async () => {
    // (reuse this file's existing render helper + MSW handler for /api/actions;
    // ensure the seeded action has path: '1.1.1')
    renderActions()
    const link = await screen.findByRole('link', { name: '#1.1.1' })
    expect(link).toHaveAttribute('href', '/items/1.1.1')
  })
```
  In `ui/src/pages/Search.test.tsx`, add `path: '2.1'` to one seeded result and:
```tsx
  it('links a search result to its item lineage page', async () => {
    renderSearch('auth') // reuse this file's helper + query that returns the result
    const link = await screen.findByRole('link', { name: '#2.1' })
    expect(link).toHaveAttribute('href', '/items/2.1')
  })
```
  In `ui/src/pages/SystemStatus.test.tsx`, the LLM Infra detail view renders each subcall's `sc.item`. Seed an existing LLM-call-detail MSW handler/fixture so one subcall has a path-shaped `item` (e.g. `item: '5.1'`) and one has a free-text `item` (e.g. `item: 'relevance batch'`), open the detail/subcall view as that file's tests already do, then:
```tsx
  it('links a path-shaped subcall item to its lineage page', async () => {
    // reuse this file's render helper + the LLM call detail open flow; ensure the
    // seeded detail has subcalls [{ item: '5.1', ... }, { item: 'relevance batch', ... }]
    await openLlmCallDetail() // existing helper / click sequence in this file
    const link = await screen.findByRole('link', { name: '#5.1' })
    expect(link).toHaveAttribute('href', '/items/5.1')
    // free-text item stays a plain label, not a link
    expect(screen.queryByRole('link', { name: /relevance batch/ })).toBeNull()
  })
```
  (If `SystemStatus.test.tsx` has no reusable detail-open helper, mirror the click sequence its existing subcall test uses — do not invent a new fixture harness.)

- [ ] **Step 2: Run test to verify it fails**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/pages/ActionItems.test.tsx src/pages/Search.test.tsx src/pages/SystemStatus.test.tsx`  Expected: `Unable to find role="link" with name #1.1.1` / `#2.1` / `#5.1`.

- [ ] **Step 3: Write minimal implementation**
  - `useActions.ts`: add `path?: string` to the `Action` interface (and ensure the actions API maps it through; the backend `Item.path` is already serialized).
  - `ActionItems.tsx` (`ActionRow`): wrap/append a path link. Inside the `min-w-0 flex-1` block, before the summary, add:
```tsx
        {action.path && (
          <Link to={`/items/${action.path}`} className="mr-2 font-mono text-xs text-primary hover:underline">
            #{action.path}
          </Link>
        )}
```
  Add `import { Link } from 'react-router-dom'` at the top.
  - `TriageDetail.tsx`: **Deferred-but-gated** (see table above — `TriageCard` carries `item_id` but no lineage `path`). Render `#{path} → /items/{path}` near the summary header **only behind a presence gate** on `c.card_content.item_path` (or `c.item_path`), e.g. `{(c.card_content.item_path) && <Link to={`/items/${c.card_content.item_path}`} className="font-mono text-xs text-primary hover:underline">#{String(c.card_content.item_path)}</Link>}`. This renders nothing today (payload lacks the field) and lights up automatically if the card endpoint later resolves the item's path. No test asserts it (no path in the fixture).
  - `Search.tsx`: in the result row, render `{r.path && <Link to={`/items/${r.path}`} className="font-mono text-xs text-primary hover:underline">#{r.path}</Link>}`, and add `path?: string` to the search-result TS type. The backend must return `path`: in `src/workbench/api/items.py` `search_items` (~line 52), add `path` to the SELECT column list (after `action_source`) and add `"path": r.get("path"),` to the `results.append({...})` dict (~line 96). Re-run `tests/test_items_search.py` to keep it green.
  - `Ingestion.tsx`: **Deferred-but-gated** (see table above — `ActivityItem` in `useStats.ts` has no `path`). In the funnel/activity row (where `item.id`/`item.summary` render), add a presence-gated link `{(item as { path?: string }).path && <Link to={`/items/${(item as { path?: string }).path}`} className="font-mono text-xs text-primary hover:underline">#{(item as { path?: string }).path}</Link>}`. This renders nothing today (the `/api/stats/activity` payload lacks `path`) and lights up once the activity payload includes it. No test asserts it (no path in the fixture). Add `import { Link } from 'react-router-dom'` if not already present.
  - `SystemStatus.tsx`: **Tested.** Where subcall items render (the `detail.subcalls.map(...)` button showing `{sc.item}`, ~line 1054), if `sc.item` matches a path shape (`/^\d+(\.\d+)*$/`), render it as `<Link to={`/items/${sc.item}`} className="font-mono text-primary hover:underline">#{sc.item}</Link>` instead of a plain label; otherwise keep the plain `{sc.item}` label. Add `import { Link } from 'react-router-dom'` if not already present. (After Task 10, `sc.item` is a real path id for stamped calls, so this lights up live.)

- [ ] **Step 4: Run test to verify it passes**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui exec vitest run src/pages/ActionItems.test.tsx src/pages/Search.test.tsx src/pages/SystemStatus.test.tsx`  Expected: PASS. If `Search` needs the backend to return `path`, also re-run `$HOME/.venv/workbench/bin/python -m pytest tests/test_items_search.py -v --tb=short` and keep it green.

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "feat(ui): link items/actions to /items/{path} across surfaces"`

---

## Task 15: Full-suite verification (backend + UI)

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**  Run: `$HOME/.venv/workbench/bin/python -m alembic upgrade head && $HOME/.venv/workbench/bin/python -m pytest tests/ -v --tb=short`  Expected: all pass (baseline ~643 + the new lineage tests; no regressions).

- [ ] **Step 2: Lint the backend**  Run: `$HOME/.venv/workbench/bin/python -m ruff check src/ tests/`  Expected: no errors.

- [ ] **Step 3: Run the full UI suite**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run test`  Expected: all pass (baseline ~498 + new ItemPage/useItem/link tests).

- [ ] **Step 4: Typecheck + build the UI**  Run: `PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH npm --prefix ui run build`  Expected: `tsc -b` clean, Vite build succeeds.

- [ ] **Step 5: Commit**  Run: `git add -A && git commit -m "test: full backend + UI suites green for item lineage" --allow-empty`

---

## Notes for the executing engineer

- **Migration number drift:** the source spec text says "latest is 011, new migration is 012." The repo's real latest is `013` (`013_llm_calls.py`). This plan uses `014` with `down_revision = "013"`. Verify with `ls src/workbench/migrations/versions/` before writing.
- **Test DB schema:** `tests/conftest.py` only TRUNCATEs; it never creates the schema. Run `alembic upgrade head` against `postgres://workbench:workbench@localhost:5432/workbench` once before the DB-touching tests (Tasks 2–11) and again in Task 15.
- **Allocation seam discipline (D1/D4):** never set `path` from a call site and never UPDATE `path` after insert. Only `create_root`/`allocate_child` write `seq`/`path`. `save_item` carries them through but is used only for legacy/parentless paths.
- **Route ordering:** register `GET /items/{path}` after the static `/items/search` route so FastAPI's static-before-dynamic matching keeps search working.
