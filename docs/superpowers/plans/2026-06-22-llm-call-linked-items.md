# LLM-Call Linked Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an LLM call's real persisted item IDs as clickable chips (`#{id} · {summary}`) in the LLM-call detail dialog, opening the existing item-detail popup. Works for batched and non-batched calls.

**Architecture:** A new `EntityLinkStore.linked_items_for_correlation` joins `entity_item_links` (by the call's `correlation_id`) to `items`. The LLM detail endpoint includes the result as `linked_items`. The detail dialog renders them as `ItemLink` chips (→ `?item=<id>` popup).

**Tech Stack:** FastAPI + asyncpg (server); React 19 + TypeScript (client); pytest + vitest.

## Global Constraints

- Server tests: `~/.venv/workbench/bin/python -m pytest <path> -v`
- Client tests + typecheck need node v20: prefix with
  `PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH"`.
  - test file: `cd ui && PATH=... node_modules/.bin/vitest run <file>`; typecheck `cd ui && PATH=... npx tsc -b`
- Branch `feature/llm-call-linked-items`. Conventional commits, scope `api`/`storage`/`ui`, no task IDs.
- The linkage is **call-level** (correlation → the call's item set), NOT per-subcall. Do not attempt `#N → exact item` mapping.
- `entity_links` is the only reader/writer of `entity_item_links`; the new read lives there.
- Reuse the existing `ItemLink` (`ui/src/components/ItemLink.tsx`) and the app-root `ItemDetailDialog`; do not add a new click/navigation path.

---

### Task 1: Backend — `EntityLinkStore.linked_items_for_correlation`

**Files:**
- Modify: `src/workbench/storage/base.py` (add `LinkedItem` + abstract method)
- Modify: `src/workbench/storage/postgres/entity_links.py` (implement)
- Test: `tests/test_entity_links_linked_items.py`

**Interfaces:**
- Produces: `EntityLinkStore.linked_items_for_correlation(correlation_id: str | None) -> list[LinkedItem]` where `LinkedItem` is a frozen dataclass `{id: int, path: str, summary: str}`. Returns `[]` for `None`/unknown correlation. Task 2 consumes it.

- [ ] **Step 1: Write the failing test**

> Pattern (verified): DB tests use the async `stores` fixture from `tests/conftest.py`. Seed an item with `stores.items.create_root(Item(...))` (allocates `path`/`id`), link it with `stores.entity_links.record_by_correlation("llm_call", corr, [item.path])`, then read it back. Use `pytestmark = pytest.mark.asyncio`.

Create `tests/test_entity_links_linked_items.py`:

```python
# tests/test_entity_links_linked_items.py
import pytest

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
)

pytestmark = pytest.mark.asyncio


async def _seed_item(stores, summary: str) -> Item:
    return await stores.items.create_root(
        Item(
            source_type="diff",
            source_id=f"D{summary}",
            summary=summary,
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
        )
    )


async def test_linked_items_for_correlation_returns_joined_items(stores):
    a = await _seed_item(stores, "alpha")
    b = await _seed_item(stores, "beta")
    await stores.entity_links.record_by_correlation(
        "llm_call", "corr-1", [a.path, b.path]
    )

    out = await stores.entity_links.linked_items_for_correlation("corr-1")

    by_id = {li.id: li for li in out}
    assert set(by_id) == {a.id, b.id}
    assert by_id[a.id].summary == "alpha"
    assert by_id[a.id].path == a.path


async def test_linked_items_for_correlation_empty_cases(stores):
    assert await stores.entity_links.linked_items_for_correlation(None) == []
    assert await stores.entity_links.linked_items_for_correlation("nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_entity_links_linked_items.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'linked_items_for_correlation'`)

- [ ] **Step 3: Add `LinkedItem` + the abstract method (base.py)**

In `src/workbench/storage/base.py`, near the `EntityLink` dataclass (~line 381), add:

```python
@dataclass(frozen=True)
class LinkedItem:
    id: int
    path: str
    summary: str
```

Add the abstract method inside `class EntityLinkStore(ABC)` (after `for_entity`):

```python
    @abstractmethod
    async def linked_items_for_correlation(
        self, correlation_id: str | None
    ) -> list[LinkedItem]:
        """Items linked to an entity by correlation_id, joined to items for the
        summary. Empty list when correlation_id is None or resolves to nothing."""
        ...
```

(Ensure `LinkedItem` is exported if `base.py` defines an `__all__`; otherwise the class definition is enough.)

- [ ] **Step 4: Implement it (entity_links.py)**

In `src/workbench/storage/postgres/entity_links.py`, import `LinkedItem` from `workbench.storage.base` (add to the existing import) and add the method to `PgEntityLinkStore`:

```python
    async def linked_items_for_correlation(
        self, correlation_id: str | None
    ) -> list[LinkedItem]:
        if correlation_id is None:
            return []
        rows = await self.pool.fetch(
            """SELECT e.item_id AS id, e.item_path AS path, i.summary
                 FROM entity_item_links e
                 JOIN items i ON i.id = e.item_id
                WHERE e.entity_type = 'llm_call' AND e.correlation_id = $1
                ORDER BY e.item_id""",
            correlation_id,
        )
        return [
            LinkedItem(id=r["id"], path=r["path"], summary=r["summary"]) for r in rows
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_entity_links_linked_items.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/workbench/storage/base.py src/workbench/storage/postgres/entity_links.py tests/test_entity_links_linked_items.py
git commit -m "feat(storage): EntityLinkStore.linked_items_for_correlation"
```

---

### Task 2: Backend — LLM detail endpoint returns `linked_items`

**Files:**
- Modify: `src/workbench/api/llm.py` (`_detail_view` + `get_call_detail`)
- Test: `tests/test_llm_linked_items_api.py`

**Interfaces:**
- Consumes: `linked_items_for_correlation` (Task 1).
- Produces: `GET /api/llm/calls/{id}` response JSON gains `linked_items: [{id, path, summary}]` (`[]` when the call has no correlation/links). Task 3 consumes it.

- [ ] **Step 1: Write the failing test**

> Mirror the app/stores wiring of `tests/test_llm_api.py` (build `FastAPI()`, `include_router(llm.router)`, `app.state.stores = stores`, drive with `httpx.AsyncClient`/`ASGITransport`). Seed an `LlmCallRecord` via `stores.llm_calls.save(...)` with a `correlation_id`, seed a linked item, then GET the detail. Read `tests/test_llm_api.py` for the exact `LlmCallRecord` constructor fields and `save` signature before writing — match them.

Create `tests/test_llm_linked_items_api.py`:

```python
# tests/test_llm_linked_items_api.py
import pytest
from httpx import AsyncClient, ASGITransport

from workbench.domain import Item, ItemCategory, ItemOrigin, Priority, ItemStatus

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import llm as llm_api

    app = FastAPI()
    app.include_router(llm_api.router)
    app.state.stores = stores
    return app


async def test_detail_includes_linked_items(stores):
    item = await stores.items.create_root(
        Item(
            source_type="diff", source_id="D1", summary="the linked item",
            category=ItemCategory.ACTION_ITEM, origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2, status=ItemStatus.ACTIVE,
        )
    )
    call = await _seed_call(stores, correlation_id="corr-x")
    await stores.entity_links.record_by_correlation("llm_call", "corr-x", [item.path])

    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/llm/calls/llm_{call.id}")
    assert resp.status_code == 200
    linked = resp.json()["linked_items"]
    assert linked == [{"id": item.id, "path": item.path, "summary": "the linked item"}]


async def test_detail_linked_items_empty_without_correlation(stores):
    call = await _seed_call(stores, correlation_id=None)
    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/llm/calls/llm_{call.id}")
    assert resp.status_code == 200
    assert resp.json()["linked_items"] == []
```

> Implement `_seed_call(stores, correlation_id)` to build + `save` a minimal `LlmCallRecord` (copy the required fields from `tests/test_llm_api.py`'s existing call-seeding helper; set `correlation_id=`). Return the saved record (with `.id`).

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_llm_linked_items_api.py -v`
Expected: FAIL (`KeyError: 'linked_items'`)

- [ ] **Step 3: Include `linked_items` in the detail view**

In `src/workbench/api/llm.py`, change `_detail_view` to accept the linked items, and fetch them in `get_call_detail`:

```python
def _detail_view(rec, linked_items: list[dict]) -> dict:
    """Map LlmCallRecord to the detail-view JSON shape (prompt + subcalls)."""
    return {
        "sysPrompt": rec.system_prompt or "",
        "subcalls": [s.model_dump() for s in rec.subcalls],
        "linked_items": linked_items,
    }
```

In `get_call_detail`, after `rec` is fetched and the `None` check, before returning:

```python
    links = await request.app.state.stores.entity_links.linked_items_for_correlation(
        rec.correlation_id
    )
    linked_items = [{"id": li.id, "path": li.path, "summary": li.summary} for li in links]
    return _detail_view(rec, linked_items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_llm_linked_items_api.py tests/test_llm_api.py -v`
Expected: PASS (new tests pass; existing llm api tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/workbench/api/llm.py tests/test_llm_linked_items_api.py
git commit -m "feat(api): include linked_items in LLM call detail"
```

---

### Task 3: Frontend — "Linked items" chips in the LLM detail dialog

**Files:**
- Modify: `ui/src/pages/SystemStatus.tsx` (`LLMCallDetailData` type, detail default, dialog section, import `ItemLink`)
- Modify: `ui/src/pages/SystemStatus.test.tsx` (fixtures + tests)

**Interfaces:**
- Consumes: `GET /api/llm/calls/{id}` `linked_items` (Task 2); `ItemLink` (existing).
- Produces: a "Linked items" section of clickable chips in the LLM detail dialog.

- [ ] **Step 1: Write the failing test**

In `ui/src/pages/SystemStatus.test.tsx`, add `linked_items` to the LLM detail fixtures and a test. Add to `LLM_DETAIL` (non-batched) and `LLM_DETAIL_BATCHED`:

```ts
  linked_items: [
    { id: 6702, path: '6702', summary: 'fix the thing' },
    { id: 6703, path: '6703', summary: 'another item' },
  ],
```

(For the non-batched `LLM_DETAIL`, use a single entry `[{ id: 7001, path: '7001', summary: 'solo item' }]`.)

Add a test (near the other LLM detail tests):

```tsx
  it('shows clickable linked-item chips in the call detail', async () => {
    await openLLMTab()
    await userEvent.click(screen.getAllByTestId('llm-log-row')[1])
    const dialog = await screen.findByRole('dialog')
    const section = await within(dialog).findByTestId('llm-linked-items')
    // a chip per linked item, showing "#<id> · <summary>", rendered as a button
    expect(within(section).getByRole('button', { name: /6702 · fix the thing/ })).toBeInTheDocument()
    expect(within(section).getByRole('button', { name: /6703 · another item/ })).toBeInTheDocument()
  })
```

> If the existing LLM detail tests render without a router, `ItemLink` (which calls `useSearchParams`) needs a router in the test tree. Check the top of `SystemStatus.test.tsx`: if `renderStatus`/the render helper does not already wrap in a `MemoryRouter`/`HashRouter`, wrap it (mirror how other page tests that use router hooks set up). The click→`?item` behavior itself is already covered by `ItemLink.test.tsx`; this test only asserts the chips render.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/SystemStatus.test.tsx -t "linked-item chips"`
Expected: FAIL (no `llm-linked-items` testid)

- [ ] **Step 3: Add the type + default + import**

In `ui/src/pages/SystemStatus.tsx`:

Add to the `LLMCallDetailData` interface (where `subcalls: LLMSubCall[]` is):

```ts
  linked_items: { id: number; path: string | null; summary: string }[]
```

Update the in-dialog default (currently `detailQuery.data ?? { sysPrompt: '', subcalls: [] }`):

```ts
  const detail: LLMCallDetailData = detailQuery.data ?? {
    sysPrompt: '',
    subcalls: [],
    linked_items: [],
  }
```

Add the import near the other component imports:

```ts
import { ItemLink } from '@/components/ItemLink'
```

- [ ] **Step 4: Render the "Linked items" section**

In the `LLMCallDetail` dialog, immediately after the header `</div>` (before the subcall selector block), add:

```tsx
          {detail.linked_items.length > 0 && (
            <div
              data-testid="llm-linked-items"
              style={{
                display: 'flex',
                gap: 8,
                flexWrap: 'wrap',
                alignItems: 'center',
                padding: '10px 18px',
                borderBottom: '1px solid var(--border)',
                background: 'var(--surface-lowest)',
              }}
            >
              <span className="label-mono" style={{ fontSize: 10, alignSelf: 'center' }}>
                Linked items:
              </span>
              {detail.linked_items.map((it) => (
                <ItemLink
                  key={it.id}
                  id={it.id}
                  className="rounded-sm border border-border px-1.5 py-px text-[11px]"
                >
                  #{it.id} · {it.summary}
                </ItemLink>
              ))}
            </div>
          )}
```

- [ ] **Step 5: Run test to verify it passes + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/SystemStatus.test.tsx`
Expected: typecheck clean; SystemStatus tests PASS

- [ ] **Step 6: Full client suite**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/SystemStatus.tsx ui/src/pages/SystemStatus.test.tsx
git commit -m "feat(ui): linked-item chips in LLM call detail (clickable to item popup)"
```

---

### Task 4: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suites**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_entity_links_linked_items.py tests/test_llm_linked_items_api.py tests/test_llm_api.py -v`
Expected: all PASS

- [ ] **Step 2: Client suite + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all PASS

- [ ] **Step 3: Confirm spec "Files touched" all changed**

Verify each file in the design's "Files touched" was modified; note deviations.

---

## Self-Review

**Spec coverage:** store method → Task 1; endpoint `linked_items` → Task 2; dialog chips + type + default + import → Task 3; verification → Task 4. All covered.

**Type/interface consistency:** `LinkedItem{id,path,summary}` (Task 1) → endpoint serializes `{id,path,summary}` (Task 2) → TS `linked_items: {id:number; path:string|null; summary:string}[]` (Task 3). `linked_items_for_correlation(correlation_id|None)` signature consistent across base/impl/caller. The chip uses the existing `ItemLink id={number}` → `?item=<id>` popup (no new click path). Subcall selector buttons untouched (plain index labels from the prior fix).

**Placeholder scan:** every step has complete code/commands; node-20 PATH on all client commands. The two backend tests note "mirror `test_llm_api.py`/conftest" for the exact `LlmCallRecord`/`save` fields rather than guessing them — that is a directed lookup against real code, not a vague placeholder.
