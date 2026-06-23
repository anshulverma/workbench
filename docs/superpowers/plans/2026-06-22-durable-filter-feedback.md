# Durable Server-Backed Filter Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make filter feedback (changing a stage's classification) durable on the server — persist a correction + tuning task, load them on /actions and the FunnelStage receipt, make Apply update the filter rule's prompt server-side, fully retire the `WBFeedback` localStorage singleton, and fix the throughput chart metric names.

**Architecture:** Extend the existing int-based `feedback_corrections`/`filter_tuning_tasks` tables with typed columns; extend the domain models + Pg store + the (already-existing-but-unused) `/api/feedback/*` hooks; rewire `FunnelStage`/`ActionItems`/`Filters`/`FilterDetailDialog`/`FilterTuningCard` to the server hooks; delete `feedback-store.ts`.

**Tech Stack:** FastAPI + asyncpg + Alembic + Pydantic (server); React 19 + TS + TanStack Query (client); pytest + vitest.

## Global Constraints

- Server tests: `~/.venv/workbench/bin/python -m pytest <path> -v`. Migrations: `~/.venv/workbench/bin/python -m alembic upgrade head` (DB-backed tests run against the test DB; conftest `stores` fixture).
- Client tests + typecheck need node v20: prefix with `PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH"`; test a file `cd ui && PATH=... node_modules/.bin/vitest run <file>`; typecheck `cd ui && PATH=... npx tsc -b`.
- Branch `feature/durable-filter-feedback`. Conventional commits, scope `api`/`storage`/`ui`/`db`. No task IDs.
- snake_case on the wire (DB/API/JSON); camelCase in older client code is renamed to snake_case reads.
- A filter stage's `filterId` == `String(filter_rules.id)` (int). Enrichers are `en_<id>` and are not editable, so corrections/tasks only target real filter rules.
- The server hooks already exist in `ui/src/hooks/useFeedback.ts` (`useCorrections`, `useTuningTasks`, `useAddCorrection`, `useCreateTuningTask`, `useUpdateTuningTask`, `useDeleteCorrection`, `useDeleteTuningTask`) — this plan EXTENDS their types + adds an Apply helper, and removes `useFeedbackStore`.

## The server ↔ client field mapping (used across slices — keep identical)

Extended `FilterTuningTask` / `ServerTuningTask` (snake_case): `id, rule_id?, filter_id, item_id, item_summary, from_outcome, to_outcome, from_label, to_label, filter_prompt, proposed_prompt, kind, correction_ids, status, created_at, resolved_at`.
Extended `FeedbackCorrection` / `ServerCorrection`: `id, item_id, rule_id?, filter_id, item_summary, original_action(=from outcome), corrected_action(=to outcome), from_label, to_label, reason, created_at`.

---

### Task 1: DB migration + domain models + store (typed columns)

**Files:**
- Create: `src/workbench/migrations/versions/017_feedback_typed_columns.py`
- Modify: `src/workbench/domain/feedback.py`
- Modify: `src/workbench/storage/postgres/feedback.py`
- Test: `tests/test_feedback_store_typed.py`

- [ ] **Step 1: Write the failing store test**

Create `tests/test_feedback_store_typed.py`:

```python
# tests/test_feedback_store_typed.py
import pytest

from workbench.domain import FeedbackCorrection, FilterTuningTask

pytestmark = pytest.mark.asyncio


async def test_correction_roundtrips_typed_fields(stores):
    c = await stores.feedback.add_correction(
        FeedbackCorrection(
            item_id=1, filter_id="5", item_summary="fix the thing",
            original_action="drop", corrected_action="include",
            from_label="Drop", to_label="Keep", reason="user override",
        )
    )
    assert c.id is not None
    got = await stores.feedback.get_corrections(item_id=1)
    assert got[0].filter_id == "5"
    assert got[0].item_summary == "fix the thing"
    assert got[0].from_label == "Drop"
    assert got[0].to_label == "Keep"


async def test_task_roundtrips_typed_fields(stores):
    t = await stores.feedback.add_task(
        FilterTuningTask(
            filter_id="5", item_id=1, item_summary="fix the thing",
            from_outcome="drop", to_outcome="include",
            from_label="Drop", to_label="Keep",
            filter_prompt="Drop noise", proposed_prompt="Drop noise but keep X",
            kind="filter-tuning", correction_ids=[1], status="open",
        )
    )
    assert t.id is not None and t.rule_id is None
    got = await stores.feedback.get_tasks(status="open")
    row = next(x for x in got if x.id == t.id)
    assert row.filter_id == "5"
    assert row.item_summary == "fix the thing"
    assert row.from_outcome == "drop" and row.to_outcome == "include"
    assert row.proposed_prompt == "Drop noise but keep X"
    assert row.correction_ids == [1]


async def test_update_task_sets_resolved_at(stores):
    t = await stores.feedback.add_task(
        FilterTuningTask(filter_id="5", item_id=1, proposed_prompt="p",
                         correction_ids=[], status="open")
    )
    updated = await stores.feedback.update_task(t.id, "applied")
    assert updated.status == "applied" and updated.resolved_at is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_feedback_store_typed.py -v`
Expected: FAIL (`TypeError`/unexpected keyword `filter_id` on the domain model, or missing column)

- [ ] **Step 3: Write the migration**

Create `src/workbench/migrations/versions/017_feedback_typed_columns.py`:

```python
"""Typed display columns on feedback_corrections + filter_tuning_tasks.

Adds the fields the UI's correction/tuning-task cards need (filter_id string,
item_summary, from/to outcomes+labels, filter_prompt, kind) so feedback can be
server-authoritative instead of client localStorage. rule_id becomes nullable on
filter_tuning_tasks (we key by the string filter_id). All adds are nullable so
existing rows/inserts keep working.

Revision ID: 017
Revises: 016
Create Date: 2026-06-22
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN filter_id TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN item_summary TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN from_label TEXT NULL")
    op.execute("ALTER TABLE feedback_corrections ADD COLUMN to_label TEXT NULL")

    op.execute("ALTER TABLE filter_tuning_tasks ALTER COLUMN rule_id DROP NOT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN filter_id TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN item_id BIGINT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN item_summary TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN from_outcome TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN to_outcome TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN from_label TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN to_label TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN filter_prompt TEXT NULL")
    op.execute("ALTER TABLE filter_tuning_tasks ADD COLUMN kind TEXT NULL")


def downgrade() -> None:
    for col in ("from_label", "to_label", "item_summary", "filter_id"):
        op.execute(f"ALTER TABLE feedback_corrections DROP COLUMN IF EXISTS {col}")
    for col in (
        "kind", "filter_prompt", "to_label", "from_label", "to_outcome",
        "from_outcome", "item_summary", "item_id", "filter_id",
    ):
        op.execute(f"ALTER TABLE filter_tuning_tasks DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE filter_tuning_tasks ALTER COLUMN rule_id SET NOT NULL")
```

Apply it: `~/.venv/workbench/bin/python -m alembic upgrade head`

- [ ] **Step 4: Extend the domain models**

In `src/workbench/domain/feedback.py`, add the new optional fields and relax `rule_id`:

```python
class FeedbackCorrection(BaseModel):
    id: int | None = None
    item_id: int
    rule_id: int | None = None
    filter_id: str | None = None
    item_summary: str | None = None
    original_action: str
    corrected_action: str
    from_label: str | None = None
    to_label: str | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FilterTuningTask(BaseModel):
    id: int | None = None
    rule_id: int | None = None          # was required int; now optional (key by filter_id)
    filter_id: str | None = None
    item_id: int | None = None
    item_summary: str | None = None
    from_outcome: str | None = None
    to_outcome: str | None = None
    from_label: str | None = None
    to_label: str | None = None
    filter_prompt: str | None = None
    proposed_prompt: str
    kind: str | None = None
    correction_ids: list[int] = Field(default_factory=list)
    status: str = "open"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
```

- [ ] **Step 5: Extend the store INSERTs + mappers**

In `src/workbench/storage/postgres/feedback.py`: retype the int-id params (`get_corrections(item_id: int | None=None)`, `delete_correction(correction_id: int)`, `update_task(task_id: int, ...)`, `delete_task(task_id: int)`), extend the two INSERT column lists + the two `_row_to_*` mappers with the new fields. New `add_correction`:

```python
    async def add_correction(self, correction: FeedbackCorrection) -> FeedbackCorrection:
        row = await self.pool.fetchrow(
            """INSERT INTO feedback_corrections
               (item_id, rule_id, filter_id, item_summary, original_action,
                corrected_action, from_label, to_label, reason, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
            correction.item_id, correction.rule_id, correction.filter_id,
            correction.item_summary, correction.original_action,
            correction.corrected_action, correction.from_label,
            correction.to_label, correction.reason, correction.created_at,
        )
        correction.id = row["id"]
        return correction
```

New `add_task`:

```python
    async def add_task(self, task: FilterTuningTask) -> FilterTuningTask:
        row = await self.pool.fetchrow(
            """INSERT INTO filter_tuning_tasks
               (rule_id, filter_id, item_id, item_summary, from_outcome,
                to_outcome, from_label, to_label, filter_prompt, proposed_prompt,
                kind, correction_ids, status, created_at, resolved_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15)
               RETURNING id""",
            task.rule_id, task.filter_id, task.item_id, task.item_summary,
            task.from_outcome, task.to_outcome, task.from_label, task.to_label,
            task.filter_prompt, task.proposed_prompt, task.kind,
            json.dumps(task.correction_ids), task.status, task.created_at,
            task.resolved_at,
        )
        task.id = row["id"]
        return task
```

Extend `_row_to_correction` and `_row_to_task` to read every new column (e.g. `filter_id=row["filter_id"]`, `item_summary=row["item_summary"]`, `from_outcome=row["from_outcome"]`, … `kind=row["kind"]`). `update_task` already sets `resolved_at` for applied/dismissed — leave its SQL, just retype `task_id`.

- [ ] **Step 6: Run to verify it passes**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_feedback_store_typed.py tests/test_feedback_api.py -v`
Expected: PASS (new typed tests + existing feedback api tests)

- [ ] **Step 7: Commit**

```bash
git add src/workbench/migrations/versions/017_feedback_typed_columns.py src/workbench/domain/feedback.py src/workbench/storage/postgres/feedback.py tests/test_feedback_store_typed.py
git commit -m "feat(db): typed display columns on feedback corrections + tuning tasks"
```

---

### Task 2: Verify endpoints carry the rich shapes (+ test)

**Files:**
- Modify (if needed): `src/workbench/api/feedback.py`
- Test: `tests/test_feedback_api_typed.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_feedback_api_typed.py` (mirror the app/stores wiring of `tests/test_feedback_api.py` — build `FastAPI()`, `include_router(feedback.router)`, `app.state.stores = stores`, httpx `AsyncClient`/`ASGITransport`):

```python
# tests/test_feedback_api_typed.py
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _app(stores):
    from fastapi import FastAPI
    from workbench.api import feedback
    app = FastAPI(); app.include_router(feedback.router); app.state.stores = stores
    return app


async def test_post_and_get_task_with_typed_fields(stores):
    app = await _app(stores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = {
            "filter_id": "5", "item_id": 1, "item_summary": "fix the thing",
            "from_outcome": "drop", "to_outcome": "include",
            "from_label": "Drop", "to_label": "Keep",
            "filter_prompt": "Drop noise", "proposed_prompt": "Drop noise but keep X",
            "kind": "filter-tuning", "correction_ids": [], "status": "open",
        }
        r = await c.post("/api/feedback/tasks", json=body)
        assert r.status_code == 200
        tid = r.json()["id"]
        got = await c.get("/api/feedback/tasks?status=open")
        row = next(x for x in got.json() if x["id"] == tid)
        assert row["filter_id"] == "5" and row["proposed_prompt"] == "Drop noise but keep X"
        # apply -> status applied + resolved_at set
        pr = await c.patch(f"/api/feedback/tasks/{tid}?status=applied")
        assert pr.json()["status"] == "applied" and pr.json()["resolved_at"]
```

- [ ] **Step 2: Run to verify it fails (or passes)**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_feedback_api_typed.py -v`
Expected: PASS if the endpoints already pass the extended models through (they accept `FilterTuningTask`/`FeedbackCorrection` directly). If FAIL on an unknown field, the endpoint models are fine — the failure would be a store/domain gap from Task 1; fix there. (No endpoint signature change is expected.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_feedback_api_typed.py src/workbench/api/feedback.py
git commit -m "test(api): feedback endpoints carry typed correction/task fields"
```

---

### Task 3: Frontend server hook types + Apply helper

**Files:**
- Modify: `ui/src/hooks/useFeedback.ts`
- Modify: `ui/src/hooks/useFeedback.test.tsx` (create if absent)

**Interfaces produced:** extended `ServerCorrection`/`ServerTuningTask` types (the rich fields); `useApplyTuningTask()` that PATCHes the filter rule prompt then sets task status `applied`. (The other hooks already exist.)

- [ ] **Step 1: Write the failing test**

Create/extend `ui/src/hooks/useFeedback.test.tsx` with a test that `useApplyTuningTask` PATCHes `/api/filter-rules/{ruleId}/prompt` then `/api/feedback/tasks/{id}?status=applied` (local `setupServer`, assert both calls):

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { useApplyTuningTask } from './useFeedback'

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })))
beforeAll(() => server.listen()); afterEach(() => { server.resetHandlers(); _resetToken() }); afterAll(() => server.close())
const wrap = ({ children }: { children: ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useApplyTuningTask', () => {
  it('patches the filter-rule prompt then marks the task applied', async () => {
    const calls: string[] = []
    server.use(
      http.patch('/api/filter-rules/5/prompt', async ({ request }) => {
        calls.push('prompt:' + (await request.json() as { prompt: string }).prompt)
        return HttpResponse.json({ status: 'ok' })
      }),
      http.patch('/api/feedback/tasks/9', ({ request }) => {
        calls.push('status:' + new URL(request.url).searchParams.get('status'))
        return HttpResponse.json({ id: 9, status: 'applied' })
      }),
    )
    const { result } = renderHook(() => useApplyTuningTask(), { wrapper: wrap })
    await result.current.mutateAsync({ taskId: 9, ruleId: 5, prompt: 'new prompt' })
    await waitFor(() => expect(calls).toEqual(['prompt:new prompt', 'status:applied']))
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/hooks/useFeedback.test.tsx`
Expected: FAIL (`useApplyTuningTask` not exported)

- [ ] **Step 3: Extend the server types + add the Apply helper**

In `ui/src/hooks/useFeedback.ts`: extend the interfaces and add `useApplyTuningTask`. Add the rich fields:

```ts
export interface ServerCorrection {
  id: number
  item_id: number
  rule_id: number | null
  filter_id: string | null
  item_summary: string | null
  original_action: string
  corrected_action: string
  from_label: string | null
  to_label: string | null
  reason: string | null
  created_at: string
}

export interface ServerTuningTask {
  id: number
  rule_id: number | null
  filter_id: string | null
  item_id: number | null
  item_summary: string | null
  from_outcome: string | null
  to_outcome: string | null
  from_label: string | null
  to_label: string | null
  filter_prompt: string | null
  proposed_prompt: string
  kind: string | null
  correction_ids: number[]
  status: string
  created_at: string
  resolved_at: string | null
}
```

Add the Apply helper (PATCH prompt then status):

```ts
import { apiGet, apiPost, apiPatch, apiDelete } from '@/lib/api'

/** Apply a tuning task: write the proposed prompt to the filter rule, then mark applied. */
export function useApplyTuningTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ taskId, ruleId, prompt }: { taskId: number; ruleId: number; prompt: string }) => {
      await apiPatch(`/api/filter-rules/${ruleId}/prompt`, { prompt })
      return apiPatch<ServerTuningTask>(`/api/feedback/tasks/${taskId}?status=applied`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback', 'tasks'] })
      qc.invalidateQueries({ queryKey: ['filter-rules'] })
    },
  })
}
```

- [ ] **Step 4: Run to verify it passes + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/hooks/useFeedback.test.tsx`
Expected: typecheck clean (note: tsc will now flag `useFeedbackStore` consumers that read removed/renamed fields — those are fixed in Tasks 4-6; if tsc fails ONLY on not-yet-touched consumers, that's expected and resolved by later tasks. Prefer running the focused vitest here; defer full `tsc -b` to the slice that finishes the rewiring). Test PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/hooks/useFeedback.ts ui/src/hooks/useFeedback.test.tsx
git commit -m "feat(ui): rich server feedback types + useApplyTuningTask"
```

---

### Task 4: FunnelStage → server (post correction+task on change; receipt from server)

**Files:**
- Modify: `ui/src/components/funnel/FunnelStage.tsx`
- Modify: `ui/src/components/funnel/FunnelStage.test.tsx`

**What changes:** replace `fb.addOverride(...)` + `fb.overrideFor(...)` with server hooks. On the correct-classification action: `useAddCorrection().mutateAsync({item_id, filter_id, item_summary, original_action: fromOutcome, corrected_action: toOutcome, from_label, to_label})` → then `useCreateTuningTask().mutateAsync({filter_id, item_id, item_summary, from_outcome, to_outcome, from_label, to_label, filter_prompt, proposed_prompt: refinedPrompt(...), kind:'filter-tuning', correction_ids:[correction.id], status:'open'})`. The receipt shows when a correction exists for (item_id, filter_id) — read from `useCorrections(item.id)` and filter by `filter_id === stage.filterId`. The "View the filter-tuning task →" link targets the server task id (find it in `useTuningTasks('open')` by item_id+filter_id, or use the create response).

- [ ] **Step 1: Write the failing test**

Rewrite the override/receipt tests in `ui/src/components/funnel/FunnelStage.test.tsx` to drive via MSW + a router/QueryClient wrapper (no more `WBFeedback.state` seeding). Representative test:

```tsx
it('posts a correction + tuning task and shows the receipt with a task link', async () => {
  const posted: Record<string, unknown>[] = []
  server.use(
    http.get('/api/auth/token', () => HttpResponse.json({ token: 't' })),
    http.post('/api/feedback/corrections', async ({ request }) => {
      posted.push(await request.json() as Record<string, unknown>)
      return HttpResponse.json({ id: 7, item_id: 1, filter_id: 'fr_01', original_action: 'drop', corrected_action: 'include' })
    }),
    http.post('/api/feedback/tasks', () => HttpResponse.json({ id: 42, filter_id: 'fr_01', item_id: 1, status: 'open', proposed_prompt: 'p', correction_ids: [7] })),
    http.get('/api/feedback/corrections', () => HttpResponse.json([{ id: 7, item_id: 1, filter_id: 'fr_01', original_action: 'drop', corrected_action: 'include' }])),
    http.get('/api/feedback/tasks', () => HttpResponse.json([{ id: 42, filter_id: 'fr_01', item_id: 1, status: 'open', proposed_prompt: 'p', correction_ids: [7] }])),
  )
  renderStage(/* editable FunnelStage for item id 1, stage.filterId 'fr_01' */)
  await userEvent.click(screen.getByText(/keep|include/i))
  await waitFor(() => expect(posted).toHaveLength(1))
  expect(posted[0].filter_id).toBe('fr_01')
  const link = await screen.findByRole('link', { name: /view the filter-tuning task/i })
  expect(link).toHaveAttribute('href', '#/actions?tuning=42')
})
```

> Add a `renderStage` helper wrapping `<FunnelStage>` in `QueryClientProvider` (the component now uses query hooks). Keep the existing non-feedback FunnelStage tests; only the override/receipt ones change.

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/funnel/FunnelStage.test.tsx`
Expected: FAIL (still posts nothing / uses WBFeedback).

- [ ] **Step 3: Rewire FunnelStage**

In `ui/src/components/funnel/FunnelStage.tsx`: remove `useFeedbackStore`; use `useCorrections(item?.id)`, `useTuningTasks('open')`, `useAddCorrection()`, `useCreateTuningTask()`. Derive `ov` from corrections: `const ov = editable && item ? (corrections.data ?? []).find(c => c.item_id === item.id && c.filter_id === stage.filterId) ?? null : null`. The correct-action handler becomes async: post correction → post task (with `correction_ids: [correction.id]` and `proposed_prompt: refinedPrompt(stage prompt, item.summary, toOutcome, toLabel)` — move `refinedPrompt` **and its private `verb` helper** (both currently unexported in `feedback-store.ts`) into `ui/src/lib/funnel-helpers.ts` and export `refinedPrompt`; this MUST land in this task since Task 6 deletes feedback-store.ts). The receipt's task link finds the task: `const tuningTask = (tasks.data ?? []).find(t => t.item_id === item.id && t.filter_id === stage.filterId)` → `#/actions?tuning=${tuningTask.id}`. Show a pending state while mutations run. `effOutcome`/`effLabel` derive from `ov` (`ov.corrected_action`/`ov.to_label`).

- [ ] **Step 4: Run to verify it passes + focused tsc**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/funnel/FunnelStage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/funnel/FunnelStage.tsx ui/src/components/funnel/FunnelStage.test.tsx ui/src/lib/funnel-helpers.ts
git commit -m "feat(ui): FunnelStage persists corrections+tasks to the server"
```

---

### Task 5: ActionItems + FilterTuningCard → server tasks; Apply/Dismiss

**Files:**
- Modify: `ui/src/pages/ActionItems.tsx`
- Modify: `ui/src/components/FilterTuningCard.tsx`
- Modify: `ui/src/pages/ActionItems.test.tsx`, `ui/src/components/FilterTuningCard.test.tsx`

**What changes:** ActionItems loads tuning tasks via `useTuningTasks('open')` (not `feedback.openTasks()`); Apply → `useApplyTuningTask().mutate({taskId, ruleId: Number(task.filter_id), prompt: task.proposed_prompt})`; Dismiss → `useUpdateTuningTask().mutate({taskId, status:'dismissed'})`. `FilterTuningCard` reads the snake_case `ServerTuningTask` (`task.filter_id`, `task.item_summary`, `task.from_outcome`/`from_label`, `task.to_outcome`/`to_label`, `task.proposed_prompt`); `onApply`/`onDismiss` take `(taskId: number)`. The `?tuning=<id>` highlight (already added) compares `task.id === Number(tuningParam)`.

- [ ] **Step 1: Write the failing tests**

Update `FilterTuningCard.test.tsx` to pass a `ServerTuningTask` (snake_case) fixture and assert it renders `task.item_summary` + the from/to chips from `from_outcome`/`to_outcome`. Update `ActionItems.test.tsx` "renders filter tuning section" to mock `GET /api/feedback/tasks?status=open` (server) instead of seeding `WBFeedback`, and add an Apply test asserting `PATCH /api/filter-rules/{id}/prompt` + `PATCH /api/feedback/tasks/{id}?status=applied` fire. (Full MSW fixtures per the field mapping.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/ActionItems.test.tsx src/components/FilterTuningCard.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Rewire ActionItems + FilterTuningCard**

`FilterTuningCard.tsx`: change the `task` prop type to `ServerTuningTask`; read snake_case fields; `onApply`/`onDismiss: (taskId: number) => void`. `ActionItems.tsx`: replace `const feedback = useFeedbackStore(); const tuningTasks = feedback.openTasks()` with `const tuningTasks = useTuningTasks('open').data ?? []`; the section maps `FilterTuningCard` with `onApply={() => applyTask.mutate({ taskId: t.id, ruleId: Number(t.filter_id), prompt: t.proposed_prompt })}` and `onDismiss={() => updateTask.mutate({ taskId: t.id, status: 'dismissed' })}` (from `useApplyTuningTask()` + `useUpdateTuningTask()`); `highlighted={t.id === Number(tuningParam)}`; the scroll effect uses `data-task-id="${tuningParam}"` (already present).

- [ ] **Step 4: Run to verify they pass + full suite + tsc**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/ActionItems.test.tsx src/components/FilterTuningCard.test.tsx`
Expected: PASS (tsc may still flag Filters/FilterDetailDialog until Task 6).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/ActionItems.tsx ui/src/components/FilterTuningCard.tsx ui/src/pages/ActionItems.test.tsx ui/src/components/FilterTuningCard.test.tsx
git commit -m "feat(ui): ActionItems loads server tuning tasks; Apply/Dismiss to server"
```

---

### Task 6: Filters + FilterDetailDialog → server; delete WBFeedback

**Files:**
- Modify: `ui/src/pages/Filters.tsx`, `ui/src/components/funnel/FilterDetailDialog.tsx`
- Modify: `ui/src/hooks/useFeedback.ts` (remove `useFeedbackStore`)
- Delete: `ui/src/lib/feedback-store.ts`, `ui/src/lib/feedback-store.test.ts`
- Modify: `ui/src/lib/types/feedback.ts` (drop client-only types; or re-export ServerTuningTask)
- Modify: the tests for Filters/FilterDetailDialog (+ any `WBFeedback.state`-seeding test: `ItemFunnelDialog.test.tsx`)

**What changes:** `Filters.tsx`: drop the `fb.promptFor` mapping — use `r.prompt` directly (Apply has updated it server-side); `tuned` = the filter has an applied task: `const applied = useTuningTasks('applied').data ?? []; tuned: applied.some(t => t.filter_id === String(r.id))`. `FilterDetailDialog.tsx`: `feedbackForFilter(rule.id)` → `useCorrections().data` filtered by `filter_id === String(rule.id)`; `promptFor(rule.id, rule.prompt)` → `rule.prompt`; per-item override reads → from corrections. Then **delete** `feedback-store.ts` (+ test) and remove `useFeedbackStore` from `useFeedback.ts`.

- [ ] **Step 1: Write/Update the failing tests**

Update `Filters.test.tsx`: mock `GET /api/feedback/tasks?status=applied`; assert a rule with an applied task shows the "tuned" indicator and displays `r.prompt`. Update `FilterDetailDialog.test.tsx`: mock `GET /api/feedback/corrections`; assert corrections for the filter render. Update `ItemFunnelDialog.test.tsx` to drop `WBFeedback.state` seeding (MSW corrections/tasks instead).

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/Filters.test.tsx src/components/funnel/FilterDetailDialog.test.tsx src/components/funnel/ItemFunnelDialog.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Rewire + delete the store**

Rewire `Filters.tsx` + `FilterDetailDialog.tsx` per above. Remove `useFeedbackStore` from `useFeedback.ts` (and its `useSyncExternalStore`/`WBFeedback` imports). Delete the store + its test:

```bash
git rm ui/src/lib/feedback-store.ts ui/src/lib/feedback-store.test.ts
```

Reconcile `ui/src/lib/types/feedback.ts` (drop `FeedbackOverride`; the tuning-task type is now `ServerTuningTask` from the hook). Then `grep -rn "WBFeedback\|useFeedbackStore\|feedback-store" ui/src` MUST be empty.

- [ ] **Step 4: Run full suite + tsc (everything green now)**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all tests PASS; no `WBFeedback`/`feedback-store` refs remain.

- [ ] **Step 5: Commit**

```bash
git add -A ui/src
git commit -m "feat(ui): Filters/FilterDetailDialog server-backed; remove WBFeedback localStorage"
```

---

### Task 7: Throughput chart metric names (B)

**Files:**
- Modify: `ui/src/pages/ActionItems.tsx`
- Modify: `ui/src/pages/ActionItems.test.tsx`

- [ ] **Step 1: Write the failing test**

In `ActionItems.test.tsx`, assert the page requests valid metrics. Mock `/api/stats/timeseries` and capture the `metric` query param; assert the requested metrics are `ingestion_count` and `throughput` (not `incoming_actions`/`completion_rate`):

```tsx
it('requests valid throughput metric names', async () => {
  const metrics: string[] = []
  server.use(http.get('/api/stats/timeseries', ({ request }) => {
    metrics.push(new URL(request.url).searchParams.get('metric') ?? '')
    return HttpResponse.json([])
  }))
  renderActions()
  await waitFor(() => expect(metrics).toEqual(expect.arrayContaining(['ingestion_count', 'throughput'])))
  expect(metrics).not.toContain('incoming_actions')
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/ActionItems.test.tsx -t "valid throughput"`
Expected: FAIL (currently requests `incoming_actions`/`completion_rate`).

- [ ] **Step 3: Fix the metric names**

In `ui/src/pages/ActionItems.tsx`, change:
```ts
  const incoming = useMetricsTimeseries('ingestion_count', 12, 'hour')
  const completion = useMetricsTimeseries('throughput', 12, 'hour')
```
(Keep the chart labels accurate to the new metrics.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/pages/ActionItems.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/ActionItems.tsx ui/src/pages/ActionItems.test.tsx
git commit -m "fix(ui): ActionItems throughput chart uses valid metric names"
```

---

### Task 8: End-to-end verification

- [ ] **Step 1: Backend**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_feedback_store_typed.py tests/test_feedback_api_typed.py tests/test_feedback_api.py -v`
Expected: all PASS.

- [ ] **Step 2: Client + typecheck**

Run: `cd ui && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="$HOME/.cache/workbench/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all PASS.

- [ ] **Step 3: No dangling client store**

Run: `grep -rn "WBFeedback\|useFeedbackStore\|feedback-store" ui/src`
Expected: no matches.

---

## Self-Review

**Spec coverage:** migration+domain+store → Task 1; endpoints → Task 2; hook types + Apply → Task 3; FunnelStage server → Task 4; ActionItems/FilterTuningCard + Apply/Dismiss → Task 5; Filters/FilterDetailDialog + delete WBFeedback → Task 6; throughput (B) → Task 7; E2E → Task 8. All spec slices covered.

**Type consistency:** snake_case server fields (`filter_id`, `from_outcome`, `proposed_prompt`, …) flow domain → store → endpoint → `ServerCorrection`/`ServerTuningTask` → FilterTuningCard/Filters/FilterDetailDialog reads. `useApplyTuningTask({taskId,ruleId,prompt})` used by ActionItems (Task 5) is defined in Task 3. `rule_id` optional everywhere. Task ids are numbers; `?tuning=` compares `Number(tuningParam)`.

**Placeholder scan:** every code step has complete code or an exact command; component-rewrite steps cite real symbols + the exact replacement code. Cross-task `tsc -b` timing is called out (consumers compile green only after Task 6 finishes the rewiring).
