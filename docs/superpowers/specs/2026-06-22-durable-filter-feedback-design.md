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
  are removed; consumers (`FunnelStage`, `ActionItems`, `Filters`,
  `FilterDetailDialog`) rewire to server query hooks.
- **Apply** updates the filter rule's prompt via the existing
  `PATCH /api/filter-rules/{rule_id}/prompt` and marks the task `applied`.

## Key id facts (verified)

- A filter stage's `filterId` is the filter rule's integer id **stringified**
  (`Filters.tsx` maps `String(r.id)` → filterId). Enricher stages are `en_<id>`
  and are **not editable** (`FunnelStage` sets `editable={!filterId.startsWith('en_')}`),
  so corrections/tasks only ever target real filter rules → `filter_id` (string)
  resolves to `filter_rules.id` (int) for the Apply prompt-update.
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
     `rule_id` → nullable.
2. **Domain** (`domain/feedback.py`): extend `FeedbackCorrection` and
   `FilterTuningTask` with the new fields (all optional with defaults for
   back-compat).
3. **Store** (`storage/postgres/feedback.py`): `add_correction`, `add_task`,
   `get_corrections`, `get_tasks`, `update_task` read/write the new columns.
4. **Endpoints**: `/api/feedback/*` already pass the pydantic models through —
   verify no signature change needed beyond the extended models. The Apply path
   reuses the existing `PATCH /api/filter-rules/{rule_id}/prompt`.

### Frontend (retire `WBFeedback`)
1. **Hooks** (`hooks/useFeedback.ts`): keep/extend the server hooks
   (`useCorrections`/`useTuningTasks` with the now-rich `ServerCorrection` /
   `ServerTuningTask` types incl. the new fields; `useAddCorrection`, new
   `useAddTask`, `usePatchTaskStatus`, and an Apply mutation that PATCHes the
   rule prompt + task status). Add `useCorrectionsForItem(itemId)`. Remove the
   `useFeedbackStore` (localStorage) export.
2. **`FunnelStage`**: on classification change, run the add-correction →
   add-task mutation chain; the receipt + effective-outcome read from
   `useCorrectionsForItem(item.id)`; the "View the filter-tuning task →" link
   targets the **server** task id. Show a pending state while the mutation runs.
3. **`ActionItems`**: load tuning tasks from `useTuningTasks('open')`; Apply →
   prompt-update + status `applied`; Dismiss → status `dismissed`. The
   `?tuning=<id>` highlight/scroll uses the server task id.
4. **`Filters` / `FilterDetailDialog`**: use `rule.prompt` directly (Apply has
   updated it server-side); "tuned" = the filter has an `applied` task (from
   `useTuningTasks('applied')`); `FilterDetailDialog` corrections via
   `useCorrections({ filter_id })`.
5. **Remove** `ui/src/lib/feedback-store.ts` + `useFeedbackStore`; update all
   consumers + their tests.

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
`components/funnel/FilterDetailDialog.tsx`; **delete** `lib/feedback-store.ts`
(+ its test); update `FunnelStage`/`ActionItems`/`Filters`/`FilterDetailDialog`
tests; `useFeedback` test.

## Slices (for the plan)

1. Migration + domain + store (typed columns) (+ tests).
2. Endpoints verified/extended for the rich shapes (+ tests).
3. Frontend server hooks (corrections/tasks rich types, add-correction,
   add-task, patch-status, apply, corrections-for-item) (+ tests).
4. `FunnelStage` → server (post correction+task on change; receipt+link from
   server) (+ tests).
5. `ActionItems` → server tasks + Apply(prompt+status)/Dismiss (+ tests).
6. `Filters` + `FilterDetailDialog` → server (rule prompt + tuned + corrections);
   **delete `WBFeedback`/feedback-store** and finish removing all consumers (+ tests).
7. B: throughput metric names (+ test).
8. E2E verification.
