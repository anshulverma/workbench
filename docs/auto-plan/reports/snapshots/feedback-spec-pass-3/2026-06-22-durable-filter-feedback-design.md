# Durable Server-Backed Filter Feedback — Design

## Goal

Filter feedback (changing a stage's classification) must be **durable across
refresh and devices** instead of living only in the browser. Changing a
classification persists a **correction** and a **filter-tuning task** to the
server; the Action Items page and the FunnelStage receipt read from the server;
**Apply** updates the filter rule's prompt server-side. The client-only
`WBFeedback` localStorage singleton is fully retired. Separately, fix the
ActionItems throughput chart, which requests metric names the server rejects.

## Root cause (recap)

- Changing a classification (`FunnelStage`) calls `WBFeedback.addOverride` →
  writes **only** to a localStorage singleton. The server endpoints
  (`/api/feedback/corrections`, `/api/feedback/tasks`, `filter_tuning_tasks` /
  `feedback_corrections` tables) exist but are **used nowhere in the UI**.
- So tuning tasks survive only within one browser's localStorage; on the
  devserver's partitioned-cert HTTPS context they vanish on refresh. The toast
  ("Sent … as a negative example. A filter-tuning task was created") implies
  server persistence that never happens.
- Separately: `ActionItems` requests `incoming_actions` / `completion_rate`
  (bucket `hour`), but the stats allow-list is `{signal_velocity,
  ingestion_count, throughput, triage_queue_count, triaged_count}` → HTTP 422
  "invalid metric or bucket" on every poll (chart broken).

## Decisions (locked during brainstorming)

- **Model: normalize into typed columns** (not a JSON blob). Extend the existing
  feedback tables with the fields the UI needs.
- **Persist correction + tuning task** on a classification change (both durable).
- **Full retire of `WBFeedback`**: corrections, tuning tasks, AND applied prompts
  all become server-authoritative. `WBFeedback`/`useFeedbackStore`/`feedback-store.ts`
  are removed; consumers rewire to server query hooks. The **direct**
  `useFeedbackStore` consumers are: `FunnelStage`, `ActionItems`, `Filters`,
  `FilterDetailDialog` (4). Plus the dependent surfaces that must rewire with them:
  - `FilterTuningCard.tsx` — presentational, renders the rich task shape
    (`task.id`, `filterId`, `itemSummary`, `fromOutcome`/`fromLabel`,
    `toOutcome`/`toLabel`, `proposedPrompt`) and takes `onApply/onDismiss:
    (taskId: string) => void`. Retarget to the server task type: `task.id`
    becomes `number`, `filterId`/`itemSummary`/`from*`/`to*` come from the new
    typed columns, and the callbacks become `(taskId: number) => void`.
  - `ItemFunnelDialog.tsx` and `ItemDetailBody.tsx` — the two **other**
    `FunnelStage` render sites (besides `Filters`). They don't call
    `useFeedbackStore` directly but pass `editable={!filterId.startsWith('en_')…}`;
    no API change, but their tests seed `WBFeedback.state` and must be migrated
    to MSW/server fixtures.
  - `lib/types/feedback.ts` (`FeedbackOverride`, `FilterTuningTask` client
    interfaces) is coupled to the store. Repurpose `FilterTuningTask` to the
    server shape (or replace with `ServerTuningTask`) and delete
    `FeedbackOverride` (corrections are read as `ServerCorrection`).
- **Apply** updates the filter rule's prompt via the existing
  `PATCH /api/filter-rules/{rule_id}/prompt` and marks the task `applied`.

## Key id facts (verified)

- A filter stage's `filterId` is the filter rule's integer id **stringified**
  (`Filters.tsx` maps `String(r.id)` → filterId). Enricher stages are `en_<id>`
  and are **not editable**: the render sites
  (`ItemFunnelDialog.tsx`/`ItemDetailBody.tsx`) pass
  `editable={!String(s.filterId).startsWith('en_')}` (ItemDetailBody also
  excludes `'action'`), and `FunnelStage` additionally self-gates its correct
  button on `!isEnricher`. So corrections/tasks only ever target real filter
  rules → `filter_id` (string) resolves to `filter_rules.id` (int) for the Apply
  prompt-update.
- The server schema is int/`rule_id`-based and minimal; we add typed string/display
  columns and make `rule_id` nullable (we key by `filter_id`).

## Architecture & data flow

```
classification change (FunnelStage)
   POST /api/feedback/corrections {item_id, filter_id, from/to outcome+label, item_summary}
   → correction id
   POST /api/feedback/tasks {filter_id, item_id, item_summary, from/to, filter_prompt,
                             proposed_prompt, kind, correction_ids:[id], status:'open'}
   → task id ; invalidate feedback queries
   receipt (from useCorrectionsForItem) → "View the filter-tuning task →" /actions?tuning=<taskId>

ActionItems  → GET /api/feedback/tasks?status=open  (rich rows) → FilterTuningCard
  Apply  → PATCH /api/filter-rules/{ruleId}/prompt {prompt: proposed_prompt}
         + PATCH /api/feedback/tasks/{id}?status=applied
  Dismiss→ PATCH /api/feedback/tasks/{id}?status=dismissed

Filters / FilterDetailDialog → rule.prompt is the live (Apply-updated) prompt;
  "tuned" = filter has an applied task; corrections via GET /api/feedback/corrections
```

## Components

### Backend
1. **Migration** (new Alembic revision): add columns
   - `feedback_corrections` += `filter_id text`, `item_summary text`,
     `from_label text`, `to_label text`; `rule_id` → nullable. (`original_action`
     / `corrected_action` carry from/to outcomes; `item_id` is the int item id.)
   - `filter_tuning_tasks` += `filter_id text`, `item_id bigint`,
     `item_summary text`, `from_outcome text`, `to_outcome text`,
     `from_label text`, `to_label text`, `filter_prompt text`, `kind text`;
     `rule_id` → nullable (`ALTER COLUMN rule_id DROP NOT NULL` — today it is
     `BIGINT NOT NULL`, see migration 009; corrections' `rule_id` is already
     nullable). **Note:** `rule_id`/`item_id` on both tables were retyped to
     `bigint` in migration 011 but carry **no DB FOREIGN KEY constraint** (only
     a type match), so dropping NOT NULL is safe with no FK / orphan concern.
     None of the added columns duplicate existing ones (tasks have no
     `original_action`/`corrected_action`; corrections have no `from_outcome`/
     `to_outcome` — they reuse `original_action`/`corrected_action`).
2. **Domain** (`domain/feedback.py`): extend `FeedbackCorrection` and
   `FilterTuningTask` with the new fields (all optional with defaults for
   back-compat). **Also relax `FilterTuningTask.rule_id`** from required
   `int` to `int | None = None` (today it is a required field — the migration's
   nullable column is not enough; the pydantic model must allow `None` since we
   key by `filter_id`). `FeedbackCorrection.rule_id` is already `int | None`.
   Add the new names to `__all__` only if new top-level symbols are introduced
   (extending the two existing models needs no `__all__` change).
3. **Store** (`storage/postgres/feedback.py`): `add_correction`, `add_task`,
   `get_corrections`, `get_tasks`, `update_task` read/write the new columns
   (extend the explicit INSERT column lists + the `_row_to_correction` /
   `_row_to_task` mappers; ids stay omitted on INSERT as BIGINT identity;
   `correction_ids` stays `$N::jsonb`). **Type-signature cleanup** (pre-existing
   mismatch — fix while here): the store methods declare `str` params
   (`get_corrections(item_id: str)`, `delete_correction(correction_id: str)`,
   `update_task(task_id: str)`, `delete_task(task_id: str)`) but the endpoints
   already pass `int` (FastAPI coerces the path/query params to `int`). Retype
   these to `int | None` / `int` to match the int identity columns. No
   `add_correction(item_id=...)` server-side filter by `filter_id` exists; see
   the corrections-by-filter note in the frontend section.
4. **Endpoints**: `/api/feedback/*` already pass the pydantic models through —
   verify no signature change needed beyond the extended models. The Apply path
   reuses the existing `PATCH /api/filter-rules/{rule_id}/prompt`.

### Frontend (retire `WBFeedback`)
1. **Hooks** (`hooks/useFeedback.ts`): the server hooks **already exist** —
   extend them, don't invent new names. Existing: `useCorrections(itemId?: number)`,
   `useTuningTasks(status?: string)`, `useAddCorrection()`,
   `useCreateTuningTask()` (NOT `useAddTask`), `useUpdateTuningTask()` (status
   PATCH; NOT `usePatchTaskStatus`), `useDeleteCorrection()`,
   `useDeleteTuningTask()`. Extend the `ServerCorrection` / `ServerTuningTask`
   TS interfaces with the new typed fields (filter_id, item_summary,
   from/to outcome+label, filter_prompt, kind). Add:
   - `useCorrectionsForItem(itemId)` — thin wrapper over `useCorrections(itemId)`
     (the existing hook already accepts `item_id`).
   - an **Apply** mutation that PATCHes `/api/filter-rules/{ruleId}/prompt`
     then calls `useUpdateTuningTask`(status `applied`) — sequenced so a failed
     prompt PATCH leaves the task `open`.
   Note: `useCorrections` filters server-side by **item_id only** (the endpoint
   has no `filter_id` query param). `FilterDetailDialog`'s per-filter corrections
   must filter the full `useCorrections()` result on the new `filter_id` column
   client-side (or, if preferred, add a `filter_id` query param to
   `GET /api/feedback/corrections` + the store — note the extra surface).
   Remove the `useFeedbackStore` (localStorage) export.
2. **`FunnelStage`**: on classification change, run the add-correction →
   add-task mutation chain; the receipt + effective-outcome read from
   `useCorrectionsForItem(item.id)`; the "View the filter-tuning task →" link
   targets the **server** task id. Show a pending state while the mutation runs.
3. **`ActionItems`**: load tuning tasks from `useTuningTasks('open')`; Apply →
   prompt-update + status `applied`; Dismiss → status `dismissed`. The
   `?tuning=<id>` highlight/scroll uses the server task id.
4. **`Filters` / `FilterDetailDialog`**: use `rule.prompt` directly (Apply has
   updated it server-side — replaces today's `fb.promptFor(String(r.id), r.prompt)`);
   "tuned" = the filter has an `applied` task (from `useTuningTasks('applied')`),
   matched by `task.filter_id === String(rule.id)` — replaces today's
   `tuned: !!fb.promptFor(String(r.id), null)`. `FilterDetailDialog` uses
   **three** store reads today, all of which must be replaced:
   `feedbackForFilter(String(rule.id))` (corrections for this filter →
   `useCorrections()` filtered by `filter_id`), `promptFor(...)` (→ `rule.prompt`
   + applied tasks), and a **per-item** `overrideFor(String(it.id),
   String(rule.id))` used to show each listed item's corrected outcome (→ look
   up that item's correction in the same `useCorrections()` set by
   `item_id` + `filter_id`). **Field-read rename (corrections are snake_case
   and reuse `original_action`/`corrected_action` for from/to outcomes, not
   `from_outcome`/`to_outcome`):** `c.itemSummary`→`c.item_summary`,
   `c.fromOutcome`→`c.original_action`, `c.toOutcome`→`c.corrected_action`,
   `c.fromLabel`→`c.from_label`, `c.toLabel`→`c.to_label`; the per-item
   `corrected.toOutcome`/`corrected.toLabel`→`corrected.corrected_action`/
   `corrected.to_label`.
5. **`FilterTuningCard`**: retype `task` to the server task shape and
   `onApply/onDismiss` to `(taskId: number) => void`. **The server emits
   snake_case, so every camelCase field read must be renamed** to the new typed
   columns: `task.filterId`→`task.filter_id`, `task.itemSummary`→
   `task.item_summary`, `task.fromOutcome`→`task.from_outcome`,
   `task.fromLabel`→`task.from_label`, `task.toOutcome`→`task.to_outcome`,
   `task.toLabel`→`task.to_label`, `task.proposedPrompt`→`task.proposed_prompt`
   (and `task.id` is already snake-neutral). `data-task-id` becomes the numeric
   server id (the `?tuning=<id>` deep-link compares against it as a string — keep
   the comparison string-coerced).
6. **Remove** `ui/src/lib/feedback-store.ts` + `useFeedbackStore`; update all
   consumers + their tests (incl. the `WBFeedback.state`-seeding tests in
   `ItemFunnelDialog.test.tsx`, `ItemDetailBody.test.tsx`, `Filters.test.tsx`,
   `ActionItems.test.tsx`, `FunnelStage.test.tsx`, and delete
   `feedback-store.test.ts`).

### B — throughput chart
`ActionItems` requests `ingestion_count` (incoming) and `throughput` (completed)
— both in the server allow-list — instead of `incoming_actions`/`completion_rate`.

## Error handling

- Feedback store optional (`stores.feedback is None` → 503) — the mutations
  surface a toast on failure; reads degrade to empty (no crash).
- Mutation chain: if the task POST fails after the correction POST, the
  correction still persisted (acceptable; the receipt reflects the correction);
  surface a toast.
- Apply: if the prompt PATCH fails, do NOT mark the task applied (keep `open`).

## Out of scope (YAGNI)

- Server-side generation of the proposed prompt (client computes `refinedPrompt`
  and posts it, as today).
- Cross-entity dedup/merge of corrections; analytics.
- Migrating any existing localStorage feedback into the server (fresh start).

## Testing

- **Backend (pytest):** migration adds columns (up); store round-trips the new
  fields on corrections + tasks; `get_tasks(status)` filters; `update_task`
  sets status + `resolved_at`; Apply prompt-update endpoint already covered.
- **Frontend (vitest):** classification change POSTs correction then task (MSW
  asserts both payloads); FunnelStage receipt + link render from server
  corrections/tasks; ActionItems lists server tasks, Apply PATCHes prompt +
  status, Dismiss PATCHes status; Filters shows the live rule prompt + tuned
  flag from applied tasks; metrics chart uses `ingestion_count`/`throughput`.
  Remove/replace `feedback-store.test.ts` and update the WBFeedback-based tests.

## Files touched

Backend: new migration; `domain/feedback.py`; `storage/postgres/feedback.py`;
(verify `api/feedback.py`); tests.
Frontend: `hooks/useFeedback.ts`; `components/funnel/FunnelStage.tsx`;
`pages/ActionItems.tsx`; `pages/Filters.tsx`;
`components/funnel/FilterDetailDialog.tsx`; `components/FilterTuningCard.tsx`
(retype to server task); `lib/types/feedback.ts` (repurpose
`FilterTuningTask` to server shape, drop `FeedbackOverride`);
`components/funnel/ItemFunnelDialog.tsx` + `components/ItemDetailBody.tsx`
(no API change, but their tests seed `WBFeedback.state`); **delete**
`lib/feedback-store.ts` (+ `lib/feedback-store.test.ts`); update
`FunnelStage`/`ActionItems`/`Filters`/`FilterDetailDialog`/`FilterTuningCard`/`ItemFunnelDialog`/`ItemDetailBody`
tests; `useFeedback` test.

## Slices (for the plan)

1. Migration + domain + store (typed columns) (+ tests).
2. Endpoints verified/extended for the rich shapes (+ tests).
3. Frontend server hooks (corrections/tasks rich types, add-correction,
   add-task, patch-status, apply, corrections-for-item) (+ tests).
4. `FunnelStage` → server (post correction+task on change; receipt+link from
   server) (+ tests).
5. `ActionItems` → server tasks + Apply(prompt+status)/Dismiss (+ tests).
6. `Filters` + `FilterDetailDialog` → server (rule prompt + tuned + corrections,
   incl. per-item corrected outcome); retype `FilterTuningCard` + repurpose
   `lib/types/feedback.ts`; migrate `ItemFunnelDialog`/`ItemDetailBody` tests;
   **delete `WBFeedback`/feedback-store** and finish removing all consumers (+ tests).
7. B: throughput metric names (+ test).
8. E2E verification.
