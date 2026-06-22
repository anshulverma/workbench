# Item-Detail Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking any item anywhere opens a deep-linkable (`?item=<id>`) Dialog with the item's rich detail, fed by real data — fixing the `#/search` crash (lean `FunnelItem` cast to rich `SearchItem`) along the way.

**Architecture:** A new id-keyed backend detail endpoint (`GET /api/items/by-id/{id}`) reuses the same rich projection as `/api/items/search`. The frontend adds an adapter that maps the API shape to the TS `SearchItem`, hooks for list + detail, a Dialog that renders the rich detail, and URL sync via `?item=<id>`. Item references across the app become an `ItemLink` that opens the dialog by `id`.

**Tech Stack:** FastAPI + asyncpg + Pydantic (server); React 19 + TypeScript + Vite + react-router (HashRouter) + TanStack Query + Radix Dialog (client); pytest + vitest + MSW.

## Global Constraints

- Server tests: `~/.venv/workbench/bin/python -m pytest <path> -v`
- Client tests + typecheck need node v20 (system node is v16); prefix with
  `PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH"`. If that dir is missing,
  re-download standalone Node v20 there (project convention).
  - run a test file: `cd ui && PATH=... node_modules/.bin/vitest run <file>`
  - typecheck: `cd ui && PATH=... npx tsc -b`
- Branch: `feature/item-detail-popup`. Conventional commits, scope `api`/`ui`, no task IDs.
- Router is **HashRouter**, so the addressable URL looks like `#/search?item=123`; use
  react-router's `useSearchParams` (it works under HashRouter) — never touch `window.location` directly.
- The detail endpoint path is exactly `GET /api/items/by-id/{item_id}` (the `by-id` segment is
  REQUIRED — `/api/items/{path}` already exists and would otherwise capture numeric ids).
- The adapter is the single source of API→UI mapping; nothing else may cast API objects to `SearchItem`.

## The API → `SearchItem` mapping (used by Tasks 1, 2, 4, 5 — keep identical)

The rich item projection (from `/api/items/search` and the new by-id endpoint) has keys:
`id, source_type, source_id, summary, category, origin, priority, status, kind("action"|"item"),
path, created_at, updated_at, tags[], llm_summary, enriched_context{}, processing_log[],
verdict{action,priority,confidence}`.

The TS `SearchItem` (`ui/src/lib/types/search.ts`, the UI contract) is:
`{id, kind: ItemKind, path?, summary, source, priority: string|null, state: ItemState,
relevance: number, tags: string[], created_at, llm_summary, context: ItemContext|null,
stages: FunnelStage[], verdict: Verdict}` where
`Verdict = {decision:'triaged'|'dropped'|'queued', priority?, confidence?, rationale: string}`.

Concrete field mapping (the adapter in Task 2 implements exactly this):
- `id` ← `id`
- `kind` ← `source_type` (cast to `ItemKind`). NOTE: `ItemKind` is the narrow union
  `'diff'|'pr'|'email'|'meeting'|'chat'`, but real `source_type` values in this deployment include
  `'meta_tasks'`/`'google_docs'`. The cast is deliberate (the adapter is the single mapping point);
  `KIND_ICON` (in `ResultRow` and the detail body) already falls back to `FileText` for unknown
  kinds, and the kind filter (Task 4) compares `it.kind === <source_type value>`, so values must be
  real `source_type` strings — NOT the `ItemKind` union members. Do not widen `ItemKind`.
- `path` ← `path ?? undefined`
- `summary` ← `summary ?? ''`
- `source` ← `source_type ?? ''`
- `priority` ← `priority ?? null`
- `state` ← `status ?? 'pending_triage'`
- `relevance` ← `0` (the API has no relevance score)
- `tags` ← `tags ?? []`
- `created_at` ← `created_at ?? ''`
- `llm_summary` ← `llm_summary ?? ''`
- `context` ← `enriched_context` if it is a non-empty object, else `null`
- `stages` ← `processing_log` mapped **per-entry** to the `FunnelStage` shape
  (`ui/src/lib/types/funnel.ts`): `FunnelStage = {filterId, outcome, reason?, confidence?, label?,
  context?, weak?}`. The API `processing_log` entries are `{label, outcome, stage, ...}` and have
  **no `filterId`** — which the detail body relies on (`SearchItemDetail` calls
  `itemLog()`/`stageTimings()` and does `String(s.filterId).startsWith('en_')` for enricher
  detection and `stageDuration` hashing). A blind cast leaves `filterId` undefined → every stage
  is mis-rendered as a filter and durations hash on `"undefined"`. So map each entry:
  `filterId ← String(e.stage ?? e.filterId ?? '')`, `outcome ← e.outcome`, `reason ← e.reason ?? e.label`,
  `label ← e.label`, `confidence ← e.confidence`, passing through the rest. (It won't crash today
  because `String(undefined)` is truthy, but the render is wrong — this mapping is the fix.)
- `verdict` ← `{ decision: api.verdict?.action === 'drop' ? 'dropped' : api.verdict?.action === 'triaged' ? 'triaged' : 'queued', priority: api.verdict?.priority ?? undefined, confidence: api.verdict?.confidence ?? undefined, rationale: '' }`

---

### Task 1: Backend — `GET /api/items/by-id/{item_id}` + shared projection helper

**Files:**
- Modify: `src/workbench/api/items.py` (extract `_row_to_search_item`; add the by-id route)
- Test: `tests/test_items_by_id_api.py`

**Interfaces:**
- Produces: `GET /api/items/by-id/{item_id}` → the rich item object (same shape each element of
  `/api/items/search`'s `results` has). `404 {"detail":"Item not found"}` when absent. Task 2's
  `useItemDetail` consumes this.

- [ ] **Step 1: Write the failing test**

> **Test pattern (verified against the real repo — DO NOT use a `client_app` fixture; it
> does not exist).** `tests/conftest.py` exposes async `pg_pool` and `stores` fixtures only.
> DB-backed API tests (e.g. `tests/test_items_related_api.py`) build a `FastAPI()` locally,
> `include_router(items_api.router)`, set `app.state.stores = stores`, and drive it with
> `httpx.AsyncClient(transport=ASGITransport(app=app))`. Seed rows via the **store**, not a
> raw INSERT: `items.path` is `NOT NULL` + `UNIQUE` (migration 014) and `items.id` is
> `GENERATED BY DEFAULT AS IDENTITY` (migration 010), so a hand-written INSERT that omits
> `path` fails the not-null constraint. `stores.items.create_root(Item(...))` allocates
> `path`/`seq` and persists `tags`/`llm_summary`/`enriched_context`/`funnel_log`/`verdict_*`
> (all are fields on the `Item` domain model). Use `pytestmark = pytest.mark.asyncio`.

Create `tests/test_items_by_id_api.py`:

```python
# tests/test_items_by_id_api.py
import pytest
from httpx import AsyncClient, ASGITransport

from workbench.domain import (
    Item,
    ItemCategory,
    ItemOrigin,
    Priority,
    ItemStatus,
)

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import items as items_api

    app = FastAPI()
    app.include_router(items_api.router)
    app.state.stores = stores
    return app


async def _seed(stores) -> Item:
    return await stores.items.create_root(
        Item(
            source_type="diff",
            source_id="D123",
            summary="fix the thing",
            category=ItemCategory.ACTION_ITEM,
            origin=ItemOrigin.AUTO_INCLUDED,
            priority=Priority.P2,
            status=ItemStatus.ACTIVE,
            tags=["infra", "urgent"],
            llm_summary="why it matters",
            enriched_context={"type": "diff", "author": "x"},
            funnel_log=[{"label": "noise filter", "outcome": "pass", "stage": "filter"}],
            verdict_action="triage",
            verdict_priority="P2",
            verdict_confidence=42,
        )
    )


async def test_get_item_by_id_returns_rich_shape(stores):
    item = await _seed(stores)
    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(f"/api/items/by-id/{item.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == item.id
    assert body["tags"] == ["infra", "urgent"]
    assert body["llm_summary"] == "why it matters"
    assert body["enriched_context"] == {"type": "diff", "author": "x"}
    assert body["processing_log"] == [
        {"label": "noise filter", "outcome": "pass", "stage": "filter"}
    ]
    assert body["verdict"] == {"action": "triage", "priority": "P2", "confidence": 42}
    assert body["source_type"] == "diff"


async def test_get_item_by_id_404_when_missing(stores):
    app = await _app(stores)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get("/api/items/by-id/999999999")
    assert resp.status_code == 404
```

> Verify the enum members against `workbench.domain.enums` before running (e.g.
> `ItemCategory.ACTION_ITEM`, `ItemOrigin.AUTO_INCLUDED`); use whichever members exist.
> The route reads `request.app.state.stores.items.pool`, matching this wiring.

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_items_by_id_api.py -v`
Expected: FAIL (404 for both — route not defined yet)

- [ ] **Step 3: Extract the shared projection helper**

In `src/workbench/api/items.py`, replace the inline `results.append({...})` block inside
`search_items` with a call to a module-level helper. Add near the top of the module (after imports):

```python
import json as _json


def _row_to_search_item(r) -> dict:
    """Map an `items` row (the rich SELECT projection) to the SearchItem-shaped dict
    returned by both /api/items/search and /api/items/by-id/{id}."""
    tags = r.get("tags")
    if isinstance(tags, str):
        tags = _json.loads(tags)
    enriched_context = r.get("enriched_context")
    if isinstance(enriched_context, str):
        enriched_context = _json.loads(enriched_context)
    funnel_log = r.get("funnel_log")
    if isinstance(funnel_log, str):
        funnel_log = _json.loads(funnel_log)
    return {
        "id": r["id"],
        "source_type": r["source_type"],
        "source_id": r["source_id"],
        "summary": r["summary"],
        "category": r["category"],
        "origin": r["origin"],
        "priority": r["priority"],
        "status": r["status"],
        "kind": "action" if r.get("action_source") else "item",
        "path": r.get("path"),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        "tags": tags or [],
        "llm_summary": r.get("llm_summary"),
        "enriched_context": enriched_context or {},
        "processing_log": funnel_log or [],
        "verdict": {
            "action": r.get("verdict_action"),
            "priority": r.get("verdict_priority"),
            "confidence": r.get("verdict_confidence"),
        },
    }
```

Then in `search_items`, replace the per-row dict construction with:

```python
    results = [_row_to_search_item(r) for r in rows]
    return {"q": q, "results": results, "total": len(results)}
```

- [ ] **Step 4: Add the by-id route**

In `src/workbench/api/items.py`, add (the literal column list matches `search_items`'s SELECT):

```python
@router.get("/items/by-id/{item_id}")
async def get_item_by_id(item_id: int, request: Request):
    """Rich detail for a single item by integer id (powers the item-detail popup)."""
    pool = request.app.state.stores.items.pool
    row = await pool.fetchrow(
        """
        SELECT id, source_type, source_id, summary, category, origin,
               priority, status, created_at, updated_at,
               tags, llm_summary, enriched_context, funnel_log,
               verdict_action, verdict_priority, verdict_confidence,
               action_source, path
          FROM items
         WHERE id = $1
        """,
        item_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _row_to_search_item(row)
```

Ensure `HTTPException` and `Request` are imported (they already are for the other routes in this file).

> Route ordering: `/items/{path}` (line ~254) is a single-segment, plain-string converter, so a
> two-segment path like `/items/by-id/5` does NOT match it (nor `/items/{path}/related`, whose
> last segment is the literal `related`). The new route is therefore structurally distinct and
> safe regardless of order. Still, declare `get_item_by_id` ABOVE `get_item_by_path` (and above
> `item_related` at line ~136) so FastAPI evaluates the literal `by-id` prefix first and the
> `{item_id:int}` coercion gives a clean 422 (not a 404 from a path lookup) on a non-numeric id.

- [ ] **Step 5: Run tests to verify they pass**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_items_by_id_api.py tests/test_items_related_api.py -v`
Expected: PASS (new tests pass; the existing items tests still pass — confirms the `search_items` refactor didn't regress)

- [ ] **Step 6: Commit**

```bash
git add src/workbench/api/items.py tests/test_items_by_id_api.py
git commit -m "feat(api): GET /api/items/by-id/{id} rich item detail (shared projection)"
```

---

### Task 2: Frontend — adapter + hooks

**Files:**
- Create: `ui/src/lib/search-adapter.ts`
- Create: `ui/src/lib/search-adapter.test.ts`
- Create: `ui/src/hooks/useItemDetail.ts`
- Create: `ui/src/hooks/useItemDetail.test.tsx`
- Modify: `ui/src/test/server.ts` (add a `/api/items/by-id/:id` MSW handler)

**Interfaces:**
- Consumes: the API shape from Task 1.
- Produces: `toSearchItem(api: ApiSearchItem): SearchItem`; `useItemsSearch(q: string)` →
  `{ data?: SearchItem[]; isPending; isError; error }` (enabled when `q.length >= 2`);
  `useItemDetail(id: number | null)` → `{ data?: SearchItem; isPending; isError; error }`
  (enabled when `id != null`). Tasks 3-5 consume these.

- [ ] **Step 1: Write the failing adapter test**

Create `ui/src/lib/search-adapter.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { toSearchItem } from './search-adapter'

const API = {
  id: 7,
  source_type: 'diff',
  source_id: 'D1',
  summary: 'fix',
  category: 'action_item',
  origin: 'phabricator',
  priority: 'P2',
  status: 'pending_triage',
  kind: 'item',
  path: null,
  created_at: '2026-06-22T00:00:00Z',
  updated_at: '2026-06-22T00:00:00Z',
  tags: ['a'],
  llm_summary: 'why',
  enriched_context: { type: 'diff', author: 'x' },
  processing_log: [{ label: 'f', outcome: 'pass', stage: 'filter' }],
  verdict: { action: 'triage', priority: 'P2', confidence: 42 },
}

describe('toSearchItem', () => {
  it('maps the rich API shape to SearchItem', () => {
    const s = toSearchItem(API)
    expect(s.id).toBe(7)
    expect(s.kind).toBe('diff')
    expect(s.source).toBe('diff')
    expect(s.state).toBe('pending_triage')
    expect(s.priority).toBe('P2')
    expect(s.tags).toEqual(['a'])
    expect(s.llm_summary).toBe('why')
    expect(s.relevance).toBe(0)
    expect(s.context).toEqual({ type: 'diff', author: 'x' })
    // processing_log entries are mapped to FunnelStage shape (stage -> filterId, label -> reason)
    expect(s.stages).toEqual([
      { filterId: 'filter', outcome: 'pass', reason: 'f', label: 'f', confidence: undefined },
    ])
    expect(s.verdict.decision).toBe('queued')
    expect(s.verdict.rationale).toBe('')
  })

  it('applies safe defaults for missing/empty fields', () => {
    const s = toSearchItem({ id: 1, summary: 'x' } as unknown as Parameters<typeof toSearchItem>[0])
    expect(s.tags).toEqual([])
    expect(s.context).toBeNull()
    expect(s.stages).toEqual([])
    expect(s.priority).toBeNull()
    expect(s.path).toBeUndefined()
    expect(s.relevance).toBe(0)
  })

  it('maps verdict action "drop" to dropped', () => {
    const s = toSearchItem({ ...API, verdict: { action: 'drop' } } as never)
    expect(s.verdict.decision).toBe('dropped')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/search-adapter.test.ts`
Expected: FAIL (cannot find `./search-adapter`)

- [ ] **Step 3: Implement the adapter**

Create `ui/src/lib/search-adapter.ts`:

```ts
// search-adapter.ts — single source of truth for mapping the rich item API shape
// (from /api/items/search and /api/items/by-id/{id}) to the UI's SearchItem type.
// Replaces the old `as unknown as SearchItem[]` cast that hid a shape mismatch.

import type { SearchItem, ItemKind, ItemState, ItemContext } from '@/lib/types/search'
import type { Verdict, FunnelStage, StageOutcome } from '@/lib/types/funnel'

interface ApiLogEntry {
  stage?: string | null
  filterId?: string | null
  outcome?: string | null
  reason?: string | null
  label?: string | null
  confidence?: number | null
}

export interface ApiSearchItem {
  id: number
  source_type?: string | null
  source_id?: string | null
  summary?: string | null
  category?: string | null
  origin?: string | null
  priority?: string | null
  status?: string | null
  kind?: string | null
  path?: string | null
  created_at?: string | null
  updated_at?: string | null
  tags?: string[] | null
  llm_summary?: string | null
  enriched_context?: Record<string, unknown> | null
  processing_log?: ApiLogEntry[] | null
  verdict?: { action?: string | null; priority?: string | null; confidence?: number | null } | null
}

function mapStage(e: ApiLogEntry): FunnelStage {
  return {
    filterId: String(e.stage ?? e.filterId ?? ''),
    outcome: (e.outcome ?? 'pass') as StageOutcome,
    reason: e.reason ?? e.label ?? undefined,
    label: e.label ?? undefined,
    confidence: e.confidence ?? undefined,
  }
}

function mapVerdict(v: ApiSearchItem['verdict']): Verdict {
  const action = v?.action
  const decision: Verdict['decision'] =
    action === 'drop' ? 'dropped' : action === 'triaged' ? 'triaged' : 'queued'
  return {
    decision,
    priority: v?.priority ?? undefined,
    confidence: v?.confidence ?? undefined,
    rationale: '',
  }
}

export function toSearchItem(api: ApiSearchItem): SearchItem {
  const ctx = api.enriched_context
  const hasCtx = !!ctx && typeof ctx === 'object' && Object.keys(ctx).length > 0
  return {
    id: api.id,
    kind: (api.source_type ?? '') as ItemKind,
    path: api.path ?? undefined,
    summary: api.summary ?? '',
    source: api.source_type ?? '',
    priority: api.priority ?? null,
    state: (api.status ?? 'pending_triage') as ItemState,
    relevance: 0,
    tags: api.tags ?? [],
    created_at: api.created_at ?? '',
    llm_summary: api.llm_summary ?? '',
    context: hasCtx ? (ctx as unknown as ItemContext) : null,
    stages: (api.processing_log ?? []).map(mapStage),
    verdict: mapVerdict(api.verdict),
  }
}
```

- [ ] **Step 4: Run to verify adapter tests pass**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/search-adapter.test.ts`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the failing hooks test**

Create `ui/src/hooks/useItemDetail.test.tsx`:

> **MSW convention (verified):** there is NO auto-started shared server — `src/test/setup.ts`
> does not call `server.listen()`. Each hook/component test creates its OWN local
> `setupServer(...)` with `beforeAll(() => server.listen())` / `afterEach` / `afterAll`, and MUST
> include a `/api/auth/token` handler because `apiGet` first fetches a bearer token (see
> `src/hooks/useItem.test.tsx`). Do NOT `import { server } from '@/test/server'` — that shared
> instance is unused and its `SEARCH_RESULTS` is the OLD UI-shape (camelCase, string ids), not the
> API shape this feature consumes.

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, beforeAll, afterEach, afterAll } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { useItemDetail, useItemsSearch } from './useItemDetail'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const RICH = {
  id: 5,
  source_type: 'diff',
  summary: 'hi',
  status: 'pending_triage',
  priority: 'P2',
  tags: ['t'],
  llm_summary: 'why',
  enriched_context: {},
  processing_log: [],
  verdict: { action: 'triage', priority: 'P2', confidence: 1 },
  path: null,
}

describe('useItemDetail', () => {
  it('fetches and adapts a single item by id', async () => {
    server.use(http.get('/api/items/by-id/5', () => HttpResponse.json(RICH)))
    const { result } = renderHook(() => useItemDetail(5), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.kind).toBe('diff')
    expect(result.current.data!.tags).toEqual(['t'])
  })

  it('is disabled when id is null', () => {
    const { result } = renderHook(() => useItemDetail(null), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('useItemsSearch', () => {
  it('is disabled below 2 chars', () => {
    const { result } = renderHook(() => useItemsSearch('a'), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('fetches and adapts results when q>=2', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: 'hi', results: [RICH], total: 1 }),
      ),
    )
    const { result } = renderHook(() => useItemsSearch('hi'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!).toHaveLength(1)
    expect(result.current.data![0].id).toBe(5)
  })
})
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/hooks/useItemDetail.test.tsx`
Expected: FAIL (cannot find `./useItemDetail`)

- [ ] **Step 7: Implement the hooks**

Create `ui/src/hooks/useItemDetail.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { toSearchItem, type ApiSearchItem } from '@/lib/search-adapter'
import type { SearchItem } from '@/lib/types/search'

const SEARCH_MIN_CHARS = 2

/** Rich detail for one item by integer id; disabled when id is null. */
export function useItemDetail(id: number | null) {
  return useQuery<SearchItem>({
    queryKey: ['item-detail', id],
    queryFn: async () => toSearchItem(await apiGet<ApiSearchItem>(`/api/items/by-id/${id}`)),
    enabled: id != null,
    staleTime: 30_000,
  })
}

/** Rich full-text item search; disabled below 2 chars. */
export function useItemsSearch(q: string, limit = 50) {
  const query = q.trim()
  return useQuery<SearchItem[]>({
    queryKey: ['items-search', { q: query, limit }],
    queryFn: async () => {
      const res = await apiGet<{ results: ApiSearchItem[] }>(
        `/api/items/search?q=${encodeURIComponent(query)}&limit=${limit}`,
      )
      return res.results.map(toSearchItem)
    },
    enabled: query.length >= SEARCH_MIN_CHARS,
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  })
}
```

- [ ] **Step 8: Fix the shared MSW fixture to the real API shape (+ by-id handler)**

> The hook tests above use a LOCAL `setupServer` with inline `server.use(...)`, so they don't need
> the shared `@/test/server`. This step exists because the spec's "Files touched" calls for the
> shared MSW fixture to reflect REAL shapes, and the current shared fixture is wrong on two counts:
> (1) `SEARCH_RESULTS` (`test/server.ts:202`) is a **bare array** of OLD UI-shape items (camelCase
> `kind`/`state`/`context`/`stages`, `verdict.decision`, and a **string** `id` like `'D12345'`),
> and (2) the existing `http.get('/api/items/search', () => HttpResponse.json(SEARCH_RESULTS))`
> handler (`test/server.ts:372`) returns that bare array, but the real endpoint returns the
> `{q, results, total}` envelope of API-shaped (snake_case, integer-id) items. No test currently
> consumes the shared `/api/items/search`, so updating it is safe.

In `ui/src/test/server.ts`:

a. Replace the `SEARCH_RESULTS` constant (line ~202) with one or more **API-shaped** entries
   (integer `id`, `source_type`, `status`, `enriched_context`, `processing_log`, `verdict.action`),
   e.g.:

```ts
const SEARCH_RESULTS = [
  {
    id: 12345,
    source_type: 'diff',
    source_id: 'D12345',
    summary: 'Fix auth middleware race condition',
    category: 'action_item',
    origin: 'phabricator',
    priority: 'P1',
    status: 'triaged',
    path: '2.1',
    created_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    updated_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    tags: ['security', 'auth'],
    llm_summary: 'Critical race condition fix in auth middleware.',
    enriched_context: { type: 'diff', author: 'alice', team: 'infra', status: 'Needs Review', url: 'https://phabricator.example.com/D12345', hunks: [] },
    processing_log: [{ stage: 'f_relevance', outcome: 'include', label: 'High relevance' }],
    verdict: { action: 'triage', priority: 'P1', confidence: 92 },
  },
]
```

b. Update the existing search handler (line ~372) to return the envelope:

```ts
    http.get('/api/items/search', () =>
      HttpResponse.json({ q: '', results: SEARCH_RESULTS, total: SEARCH_RESULTS.length }),
    ),
```

c. Add the by-id handler next to it (note `SEARCH_RESULTS` is an ARRAY — `.find`, not `.results.find`):

```ts
    http.get('/api/items/by-id/:id', ({ params }) => {
      const found = SEARCH_RESULTS.find((r) => String(r.id) === params.id)
      return found
        ? HttpResponse.json(found)
        : new HttpResponse(JSON.stringify({ detail: 'Item not found' }), { status: 404 })
    }),
```

- [ ] **Step 9: Run to verify hook tests pass + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/hooks/useItemDetail.test.tsx src/lib/search-adapter.test.ts`
Expected: typecheck clean; tests PASS

- [ ] **Step 10: Commit**

```bash
git add ui/src/lib/search-adapter.ts ui/src/lib/search-adapter.test.ts ui/src/hooks/useItemDetail.ts ui/src/hooks/useItemDetail.test.tsx ui/src/test/server.ts
git commit -m "feat(ui): SearchItem adapter + useItemDetail/useItemsSearch hooks"
```

---

### Task 3: Frontend — detail body, dialog, URL sync, app mount

**Files:**
- Create: `ui/src/components/ItemDetailBody.tsx` (extracted from `SearchItemDetail`)
- Create: `ui/src/components/ItemDetailDialog.tsx`
- Create: `ui/src/components/ItemDetailDialog.test.tsx`
- Create: `ui/src/hooks/useItemDialog.ts`
- Modify: `ui/src/App.tsx` (mount `<ItemDetailDialog />` once, inside the router)

**Interfaces:**
- Consumes: `useItemDetail` (Task 2), `useItemDialog`.
- Produces: `useItemDialog()` → `{ openItem(id: number): void; closeItem(): void; itemId: number | null }`
  (reads/writes the `?item` search param). `<ItemDetailDialog />` (no props) — self-contained,
  mounted once at app root. `ItemDetailBody({ item }: { item: SearchItem })`. Tasks 4-5 call `openItem`.

- [ ] **Step 1: Write the failing dialog test**

Create `ui/src/components/ItemDetailDialog.test.tsx`:

> Same MSW convention as Task 2: local `setupServer` with lifecycle hooks + a `/api/auth/token`
> handler (the dialog fetches detail via `apiGet`, which needs a token). The dialog also renders
> toasts/actions via `useItemActions`/`useSnoozeItem`; wrap with a `<Toaster />` if asserting toast
> text (not needed for these tests). The detail body imports nothing that requires extra providers
> beyond QueryClient + Router.

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, beforeAll, afterEach, afterAll } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { ItemDetailDialog } from './ItemDetailDialog'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function renderAt(initial: string, ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const RICH = {
  id: 5, source_type: 'diff', summary: 'the summary', status: 'pending_triage',
  priority: 'P2', tags: ['t'], llm_summary: 'why it matters', enriched_context: {},
  processing_log: [], verdict: { action: 'triage' }, path: null,
}

describe('ItemDetailDialog', () => {
  it('is closed with no ?item param', () => {
    renderAt('/search', <ItemDetailDialog />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('opens and shows item detail when ?item=<id> is present', async () => {
    server.use(http.get('/api/items/by-id/5', () => HttpResponse.json(RICH)))
    renderAt('/search?item=5', <ItemDetailDialog />)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    expect(screen.getByText('the summary')).toBeInTheDocument()
    expect(screen.getByText('why it matters')).toBeInTheDocument()
  })

  it('shows "item not found" on 404', async () => {
    server.use(
      http.get('/api/items/by-id/9', () =>
        new HttpResponse(JSON.stringify({ detail: 'Item not found' }), { status: 404 }),
      ),
    )
    renderAt('/search?item=9', <ItemDetailDialog />)
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/ItemDetailDialog.test.tsx`
Expected: FAIL (cannot find `./ItemDetailDialog`)

- [ ] **Step 3: Extract the detail body**

Create `ui/src/components/ItemDetailBody.tsx` by moving the **non-null `return (...)` JSX** from
`ui/src/components/search/SearchItemDetail.tsx` (lines ~95-262; the file is 263 lines) into a
component `ItemDetailBody({ item, onAction }: ...)`. Carry over EVERY import the moved JSX uses,
verified against the real file:
- lucide icons `GitPullRequestArrow, Mail, Calendar, MessageCircle, FileText, Sparkles` and the
  `LucideIcon` type (the null-branch `Search` icon is NOT needed — the loading/empty/404 states live
  in `ItemDetailDialog`, not the body)
- the module-level `KIND_ICON`, `PRIORITY_VARIANT`, `CTX_LABEL` consts (copy them into the body file)
- `relativeTime` (`@/lib/format`), `itemLog`, `stageTimings` (`@/lib/funnel-helpers`)
- `Mono`, `Badge`, `Button`, `Card`/`CardHeader`/`CardTitle`/`CardContent`, `StateDot`,
  `VerdictPill`, `FunnelStage` (`@/components/funnel/FunnelStage`), `ItemContext`
  (`@/components/search/contextual/ItemContext`)
- types `SearchItem` and `FunnelStage as FunnelStageType`

Keep the `ItemAction`/`onAction` handling. The body relies on `FunnelStage` shape (`s.filterId`),
which the Task 2 adapter now produces from `processing_log` (see the mapping section) — so the
processing-log section renders correctly. Signature:

```tsx
export type ItemAction = 'priority' | 'done' | 'snooze' | 'archive' | 'delete'

export function ItemDetailBody({
  item,
  onAction,
}: {
  item: SearchItem
  onAction: (itemId: number, action: ItemAction, value?: string) => void
}) {
  /* ...the existing non-null detail JSX from SearchItemDetail (header, tags,
     actions bar, llm summary, contextual payload, processing log, verdict)... */
}
```

Leave `SearchItemDetail.tsx` for now (Task 4 removes its remaining usage); it can re-export
`ItemDetailBody` or be deleted in Task 4.

- [ ] **Step 4: Implement `useItemDialog` and `ItemDetailDialog`**

Create `ui/src/hooks/useItemDialog.ts`:

```ts
import { useSearchParams } from 'react-router-dom'

/** Reads/writes the `?item=<id>` search param that drives the item-detail dialog. */
export function useItemDialog() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('item')
  const itemId = raw != null && /^\d+$/.test(raw) ? Number(raw) : null

  const openItem = (id: number) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('item', String(id))
        return next
      },
      { replace: false },
    )
  }
  const closeItem = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('item')
        return next
      },
      { replace: false },
    )
  }
  return { itemId, openItem, closeItem }
}
```

Create `ui/src/components/ItemDetailDialog.tsx`:

```tsx
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useItemDetail } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { useItemActions, useSnoozeItem } from '@/hooks/useSearchItems'
import { ItemDetailBody, type ItemAction } from './ItemDetailBody'

/** App-root item-detail popup. Driven entirely by the `?item=<id>` URL param. */
export function ItemDetailDialog() {
  const { itemId, closeItem } = useItemDialog()
  const q = useItemDetail(itemId)
  const { archive } = useItemActions()
  const snooze = useSnoozeItem()

  const onAction = (id: number, action: ItemAction, value?: string) => {
    switch (action) {
      case 'priority':
        toast.success(`Set ${id} → ${value || '—'}`)
        break
      case 'snooze':
        snooze.mutate({ itemId: id, durationMinutes: 240 })
        break
      default:
        archive.mutate(id) // done | archive | delete → soft-archive
    }
  }

  return (
    <Dialog open={itemId != null} onOpenChange={(o) => !o && closeItem()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Item {itemId}</DialogTitle>
        </DialogHeader>
        {q.isPending && itemId != null && (
          <div className="grid gap-3" data-testid="item-detail-loading">
            <Skeleton className="h-7 w-48" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
        {q.isError && (
          <div role="alert" className="p-2 text-destructive">
            {q.error instanceof ApiError && q.error.status === 404
              ? 'Item not found'
              : `Failed to load item: ${q.error instanceof ApiError ? q.error.message : 'Unknown error'}`}
          </div>
        )}
        {q.data && (
          <>
            <ItemDetailBody item={q.data} onAction={onAction} />
            {q.data.path && (
              <Link
                to={`/items/${q.data.path}`}
                onClick={closeItem}
                className="text-xs text-primary hover:underline"
              >
                open full page ↗
              </Link>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: Mount the dialog once at app root**

In `ui/src/App.tsx`, render `<ItemDetailDialog />` inside `<ErrorBoundary>` after `<Routes>` so it
overlays any route:

```tsx
import { ItemDetailDialog } from '@/components/ItemDetailDialog'
// ...
      <ErrorBoundary>
        <Routes>
          {/* ...existing routes... */}
        </Routes>
        <ItemDetailDialog />
      </ErrorBoundary>
```

- [ ] **Step 6: Run to verify dialog tests pass + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/ItemDetailDialog.test.tsx`
Expected: typecheck clean; tests PASS

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ItemDetailBody.tsx ui/src/components/ItemDetailDialog.tsx ui/src/components/ItemDetailDialog.test.tsx ui/src/hooks/useItemDialog.ts ui/src/App.tsx
git commit -m "feat(ui): item-detail Dialog driven by ?item URL param"
```

---

### Task 4: Frontend — Search page rewrite (list + dialog + type-to-search)

**Files:**
- Modify: `ui/src/pages/Search.tsx` (use `useItemsSearch`; rows open dialog; remove inline panel)
- Modify: `ui/src/pages/Search.test.tsx` (drive via `/api/items/search`; assert dialog on click)
- Modify: `ui/src/components/search/ResultRow.tsx` (row click opens dialog via `useItemDialog`)
- Delete: `ui/src/components/search/SearchItemDetail.tsx` (+ its test) — superseded by `ItemDetailBody`

**Interfaces:**
- Consumes: `useItemsSearch`, `useItemDialog`, `ResultRow`.
- Produces: a Search page that lists results and opens the shared dialog on row click; no inline
  master/detail; "type to search" empty state.

- [ ] **Step 1: Update the Search page test (failing)**

> **Verified state of `Search.test.tsx`:** it has its OWN local `setupServer` (`baseHandlers()` at
> ~line 125, started via `beforeAll(server.listen())`), its own `ALL_ITEMS` rich fixtures
> (`DIFF_ITEM`…, **OLD UI shape with string ids** like `'D12345'`), and a `renderSearch()` helper
> (~line 140) that wraps `<Search />` with `QueryClient` + `MemoryRouter(['/search'])` + `<Toaster />`.
> The whole `/api/funnel/items` + `ALL_ITEMS` + master/detail assertions are obsolete for this page.

Rework `ui/src/pages/Search.test.tsx`:
- In `baseHandlers()`, replace the `/api/funnel/items` handler with `/api/items/search` returning the
  `{q, results, total}` envelope of **API-shaped** items (snake_case, integer id), and add an
  `/api/items/by-id/:id` handler. Keep the existing `/api/auth/token` handler.
- Replace the `ALL_ITEMS`/`DIFF_ITEM`… fixtures with API-shaped fixtures (or a small `RESULT` like
  below). Delete tests that assert the inline master/detail panel, contextual-payload-by-selection,
  and keyboard nav over the old grid.
- Update `renderSearch()` to ALSO render `<ItemDetailDialog />` next to `<Search />` (inside the same
  `MemoryRouter`) so the `?item` param has a listener and row clicks open the dialog.
- Drive input via the search box and assert the dialog opens. Representative tests:

```tsx
// helper rich result
const RESULT = {
  id: 11, source_type: 'diff', summary: 'crashy item', status: 'pending_triage',
  priority: 'P2', tags: [], llm_summary: 'matters', enriched_context: {},
  processing_log: [], verdict: { action: 'triage' }, path: null,
}

it('shows a type-to-search prompt before input', () => {
  renderSearch() // existing helper that wraps with router + query client
  expect(screen.getByText(/type to search/i)).toBeInTheDocument()
})

it('lists results and opens the dialog on row click', async () => {
  server.use(
    http.get('/api/items/search', () =>
      HttpResponse.json({ q: 'cr', results: [RESULT], total: 1 }),
    ),
    http.get('/api/items/by-id/11', () => HttpResponse.json(RESULT)),
  )
  renderSearch()
  await userEvent.type(screen.getByLabelText('Search items'), 'cr')
  await waitFor(() => expect(screen.getByText('crashy item')).toBeInTheDocument())
  await userEvent.click(screen.getByText('crashy item'))
  await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  expect(screen.getByText('matters')).toBeInTheDocument()
})
```

> `renderSearch` must wrap with the same providers App uses (QueryClient + a router) AND render
> `<ItemDetailDialog />` alongside `<Search />` so the `?item` param has a listener — mirror how
> other page tests wrap, adding `<ItemDetailDialog />`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/Search.test.tsx`
Expected: FAIL (page still uses funnel endpoint + inline panel)

- [ ] **Step 3: Rewrite the Search page**

Replace `ui/src/pages/Search.tsx` body so it: uses `useItemsSearch(debouncedQ)`; renders the
title + input + kind filter + a single result list (no master/detail grid, no `selectedId`,
no `SearchItemDetail`); each `ResultRow` opens the dialog; shows "type to search" when
`debouncedQ.length < 2`. Key parts:

```tsx
import { useState, useEffect, useMemo, useRef } from 'react'
import { Search as SearchIcon, X } from 'lucide-react'
import type { SearchItem } from '@/lib/types/search'
import { useItemsSearch } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { ApiError } from '@/lib/api'
import { ResultRow } from '@/components/search/ResultRow'
import { EmptyState } from '@/components/EmptyState'
import { Mono } from '@/components/Mono'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

function useDebouncedValue<T>(value: T, delay: number): T {
  const [d, setD] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return d
}

const KINDS: Array<[string, string]> = [
  ['all', 'All'], ['diff', 'Diffs'], ['meta_tasks', 'Tasks'], ['google_docs', 'Docs'],
]

export function Search() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('all')
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQ = useDebouncedValue(q.trim(), 250)
  const searchQ = useItemsSearch(debouncedQ)
  const { openItem } = useItemDialog()

  const allItems: SearchItem[] = searchQ.data ?? []
  const filtered = useMemo(
    () => allItems.filter((it) => kind === 'all' || it.kind === kind),
    [allItems, kind],
  )

  const tooShort = debouncedQ.length < 2

  return (
    <div className="grid gap-4" data-testid="search-page">
      <div className="grid gap-1">
        <h1 className="text-lg font-semibold">Search</h1>
        <p className="m-0 text-[13px] text-muted-foreground">
          Every ingested item — click one to inspect its full detail.
        </p>
      </div>

      <div className="flex items-center gap-2.5 rounded-md border border-border bg-[var(--surface-lowest)] px-3.5 py-2.5">
        <SearchIcon size={18} className="shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search items, IDs, sources, tags…"
          aria-label="Search items"
          className="flex-1 border-0 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground"
        />
        {q && (
          <button type="button" aria-label="Clear" onClick={() => setQ('')}
            className="flex h-6.5 w-6.5 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground">
            <X size={15} />
          </button>
        )}
        <Mono className="text-xs text-muted-foreground">{filtered.length}</Mono>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {KINDS.map(([k, label]) => (
          <Button key={k} size="sm" variant={kind === k ? 'default' : 'outline'} onClick={() => setKind(k)}>
            {label}
          </Button>
        ))}
      </div>

      {tooShort ? (
        <EmptyState message="// type at least 2 characters to search" />
      ) : searchQ.isPending ? (
        <div className="grid gap-2" data-testid="search-loading">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : searchQ.isError ? (
        <div role="alert" data-testid="search-error" className="p-6 text-destructive">
          {searchQ.error instanceof ApiError && searchQ.error.status === 401
            ? 'token unavailable; check tunnel/binding'
            : `Failed to load items: ${searchQ.error instanceof ApiError ? searchQ.error.message : 'Unknown error'}`}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState message="// No items match your search" />
      ) : (
        <div role="listbox" aria-label="Search results" className="grid gap-2">
          {filtered.map((it) => (
            <ResultRow key={it.id} id={`search-row-${it.id}`} item={it} active={false} onClick={() => openItem(it.id)} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Make ResultRow open the dialog**

`ResultRow` already calls its `onClick` prop on click/Enter/Space; the Search page now passes
`onClick={() => openItem(it.id)}`. Update the inner item-id link so it ALSO opens the dialog
instead of navigating to `/items/{path}`. In `ui/src/components/search/ResultRow.tsx`, the
`{item.path && <Link to={/items/${item.path}}>}` block — leave it as the secondary "lineage"
link (it still works for items with a path) OR remove it (the whole row opens the rich dialog
now). Remove it to avoid two competing click targets:

```tsx
// delete the `{item.path && (<Link .../>)}` block; the row's onClick opens the dialog.
// Remove the now-unused `Link` import.
```

- [ ] **Step 5: Delete the superseded panel**

```bash
git rm ui/src/components/search/SearchItemDetail.tsx ui/src/components/search/SearchItemDetail.test.tsx 2>/dev/null || rm -f ui/src/components/search/SearchItemDetail.tsx ui/src/components/search/SearchItemDetail.test.tsx
```

(If `ItemDetailBody` re-exported `ItemAction` from the old file, ensure nothing else imports
`SearchItemDetail`: `grep -rn "SearchItemDetail" ui/src` must be empty.)

- [ ] **Step 6: Run Search tests + full suite + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all tests PASS (Search page + whole suite)

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/Search.tsx ui/src/pages/Search.test.tsx ui/src/components/search/ResultRow.tsx
git commit -m "feat(ui): search page opens item-detail dialog; retire inline panel"
```

---

### Task 5: Frontend — `ItemLink` + app-wide swap

**Files:**
- Create: `ui/src/components/ItemLink.tsx`
- Create: `ui/src/components/ItemLink.test.tsx`
- Modify: `ui/src/components/LiveTail.tsx`, `ui/src/pages/ActionItems.tsx`,
  `ui/src/pages/TriageDetail.tsx`, `ui/src/pages/SystemStatus.tsx`

**Interfaces:**
- Consumes: `useItemDialog`.
- Produces: `ItemLink({ id, children, className }: { id: number; children: ReactNode; className?: string })`
  — a button that opens the item dialog by id.

- [ ] **Step 1: Write the failing test**

Create `ui/src/components/ItemLink.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useSearchParams } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ItemLink } from './ItemLink'

function ParamProbe() {
  const [p] = useSearchParams()
  return <span data-testid="param">{p.get('item') ?? ''}</span>
}

describe('ItemLink', () => {
  it('sets ?item=<id> on click without navigating away', async () => {
    render(
      <MemoryRouter initialEntries={['/actions']}>
        <ItemLink id={42}>#42</ItemLink>
        <ParamProbe />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('#42'))
    await waitFor(() => expect(screen.getByTestId('param').textContent).toBe('42'))
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/ItemLink.test.tsx`
Expected: FAIL (cannot find `./ItemLink`)

- [ ] **Step 3: Implement `ItemLink`**

Create `ui/src/components/ItemLink.tsx`:

```tsx
import type { ReactNode } from 'react'
import { useItemDialog } from '@/hooks/useItemDialog'
import { cn } from '@/lib/utils'

/** A clickable item reference that opens the item-detail dialog by id (no navigation). */
export function ItemLink({
  id,
  children,
  className,
}: {
  id: number
  children: ReactNode
  className?: string
}) {
  const { openItem } = useItemDialog()
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        openItem(id)
      }}
      className={cn('font-mono text-primary hover:underline', className)}
    >
      {children}
    </button>
  )
}
```

- [ ] **Step 4: Swap the app-wide item links**

In each file below, replace the `{<id-field> && <Link to={/items/${path}}>#{path}</Link>}` block
with `<ItemLink id={<numeric id>}>#{<id>}</ItemLink>`, importing `ItemLink` and dropping the now
unused `Link` import where it was only used for item links. Use the numeric `id` available at each
site (verify the field with the noted line):

- `ui/src/pages/ActionItems.tsx` — has `action.id` (row uses `action-row-${action.id}`); replace
  the `{action.path && <Link to={/items/${action.path}}>}` block (~line 120-126) with
  `<ItemLink id={action.id}>#{action.id}</ItemLink>`.
- `ui/src/components/LiveTail.tsx` — the `{entry.path ? <Link to={/items/${entry.path}}> ...}`
  block (~line 185-191). If `entry` carries a numeric item id field, use it; if `entry` only has
  `path`, KEEP the existing `<Link to={/items/${entry.path}}>` (log lineage) — DO NOT fabricate an
  id. Note this in the report.
- `ui/src/pages/TriageDetail.tsx` — the `{itemPath && <Link to={/items/${itemPath}}>}` block
  (~line 90-95). Use the card's numeric item id if present in `c.card_content` (e.g.
  `c.card_content.item_id`); otherwise keep the existing path Link and note it.
- `ui/src/pages/SystemStatus.tsx` — the `<Link to={/items/${sc.item}}>` (~line 1060). Use a numeric
  id field if `sc` exposes one; otherwise keep the existing Link and note it.

> Rule: only convert a site to `ItemLink` when a real numeric item `id` is available there. Where a
> surface genuinely only has a `path`, leave its existing `/items/{path}` Link untouched and record
> which sites were skipped (so the final review can decide whether a backend id is worth adding).

- [ ] **Step 5: Run to verify ItemLink test + full suite + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all tests PASS

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/ItemLink.tsx ui/src/components/ItemLink.test.tsx ui/src/components/LiveTail.tsx ui/src/pages/ActionItems.tsx ui/src/pages/TriageDetail.tsx ui/src/pages/SystemStatus.tsx
git commit -m "feat(ui): ItemLink opens detail dialog; swap app-wide item links"
```

---

### Task 6: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full server + client suites**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_items_by_id_api.py -v && cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: all PASS, typecheck clean

- [ ] **Step 2: No dangling references**

Run: `grep -rn "SearchItemDetail\|as unknown as SearchItem\|/api/funnel/items" ui/src/pages/Search.tsx ui/src/components/search`
Expected: no matches (the old panel, cast, and funnel-endpoint usage are gone from the search path)

- [ ] **Step 3: Confirm spec "Files touched" all exist/changed**

Verify each file in the design's "Files touched" was created/modified; note any deviation
(e.g. LiveTail/TriageDetail/SystemStatus sites skipped for lack of a numeric id).

---

## Self-Review

**Spec coverage:** by-id endpoint → Task 1; adapter+hooks → Task 2; dialog + URL sync + app mount →
Task 3; search rewrite + type-to-search + retire panel/cast → Task 4; app-wide ItemLink → Task 5;
verification → Task 6. All slices covered.

**Type/interface consistency:** `toSearchItem(ApiSearchItem): SearchItem` used by `useItemDetail`,
`useItemsSearch` (Task 2), consumed by `ItemDetailDialog`/`ItemDetailBody` (Task 3), Search (Task 4).
`useItemDialog()` → `{ itemId, openItem, closeItem }` used by `ItemDetailDialog` (3), Search (4),
`ItemLink` (5). The dialog is mounted once at app root (Task 3) so `?item` works from every surface.

**Placeholder scan:** every code step has complete code; commands are exact with node-20 PATH.
Known judgment points are bounded by an explicit rule (Task 5 Step 4: only convert sites that
expose a numeric id; otherwise keep the existing path Link and report) rather than left vague.
