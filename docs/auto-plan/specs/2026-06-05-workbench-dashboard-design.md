# Workbench Management Dashboard — Design Spec

## Context — what exists today, what's missing, why

Today the only persistent visibility-and-management surface is the messenger-based Morning Briefing plus a thin React scaffold (`ui/`, React 18 + Vite 6 + Tailwind v3) that renders a single Action Items list against `/api/actions`, and `/api/sources` exposes only `GET` + `PATCH` (no create/delete) while `/api/memory/facts` returns a bare list and `/api/triage/respond` has no web-native confirmation flow. Source polling runs through a single global `poll_sources` interval job keyed by `source_last_polled:{adapter_type}`, and there is no per-source execution record, no server-side aggregation endpoint, and no config write-back path. This spec adds the **Management Dashboard** — a multi-page React SPA served at `/ui` that is a pure HTTP client over `/api` — together with the backend **Stats Endpoint**, `ingestion_runs` table, source CRUD with **Config Write-Back** and **Targeted Hot-Reload**, per-source **Source Job** scheduling with `source_id`-keyed **Watermark**, messenger info/edit, **Fact Curation**, and web triage respond/confirm.

## Goals

1. **Surface** every operational dimension of Workbench (triage, ingestion, sources, knowledge, messenger) on one same-origin SPA at `/ui` that reads and writes exclusively through `/api`.
2. **Aggregate** dashboard counts and time series server-side via the **Stats Endpoint** (`GET /api/stats/*`) using `COUNT ... GROUP BY` repository methods, never client-side row scans.
3. **Manage** sources end-to-end from the UI — create, edit, enable/disable, delete, and poll-now — persisting each change to `config.yml` via **Config Write-Back** and applying it live via **Targeted Hot-Reload** with no process restart.
4. **Schedule** each enabled source independently as a **Source Job** (one `CronTrigger` per source) and track its poll cursor as a `source_id`-keyed **Watermark**.
5. **Record** every source poll as an **Ingestion Run** row that backs **Source Health Status**, per-source qualified **Ingested Count**s, and the ingestion time series.
6. **Curate** learned **Preference Fact**s (edit/delete) end-to-end through `PATCH/DELETE /api/memory/facts/{id}` with a memory-service tombstone, returning 501 under `NoopMemoryLayer`.
7. **Triage** cards web-natively with numbered and free-text responses, a confirmation flow for destructive free-text, and a 409 guard against double-response.
8. **Harden** every new read endpoint with the shared **Redaction Rule** (allowlist-on-output) and every mutation with bearer auth, boundary validation, and audit logging carrying the **Correlation ID**.

## Architecture

```
                            Browser (SSH tunnel -> 127.0.0.1)
                                        |
                         GET /ui  (static SPA, vite base /ui/)
                                        |
   +------------------------- React 19 SPA (HashRouter) ---------------------------+
   |  pages/  components/ui (shadcn)  components (app)  lib/  hooks/               |
   |  TanStack Query v5 (cache, poll, pause-on-hidden, invalidate-on-mutation)    |
   |  thin fetch wrapper: getToken() -> GET /api/auth/token ; authHeaders()       |
   +------------------------------------|----------------------------------------+
                                        | fetch + Bearer token (same-origin /api)
                                        v
   +------------------------------- FastAPI /api --------------------------------+
   |  stats/*   jobs   activity   sources(+poll)   connections   adapter-types  |
   |  messenger   memory/facts(+curation)   triage(respond/confirm)   queue/dl  |
   +----|-----------------|---------------------|-------------------|-----------+
        |                 |                     |                   |
        v                 v                     v                   v
  Repositories      IngestionRunStore     Config Write-Back   Targeted Hot-Reload
  (Stores bundle)   (ingestion_runs)      ruamel round-trip   validate->instantiate
  ItemStore         written by            -> config.yml       ->write->swap (Lock)
  IngestionQueue    _poll_one_source      (atomic os.replace) app.state.sources / messenger
  JobStore                                                    scheduler.messenger
  ConfigStore (watermark, source_last_polled:{source_id})    alert_manager.messenger
        |
        v
  WorkbenchScheduler: one Source Job (CronTrigger) per enabled source
  poll_source:{source_id} -> _poll_one_source(source_id, trigger) -> pipeline.enqueue
        |
        v
  MemoryLayer provider (Noop default; Zep/Graphiti memory service in workbench-meta)
```

Flow: the SPA loads from the static `/ui` mount, fetches a bearer token from the **Token-Vending Endpoint**, then drives all reads/writes through `/api`. Read paths fan out to repository aggregation methods and the new `IngestionRunStore`; write paths (source/messenger edits) run **Config Write-Back** then **Targeted Hot-Reload** under an `asyncio.Lock`, after which the per-source **Source Job** schedule and the `app.state` provider objects reflect the change without a restart. The memory service (a separate provider, Graphiti-backed in workbench-meta) backs facts read and **Fact Curation**.

---

## Design Section 1 — Frontend Architecture & Stack

### 1.1 Stack and versions (use latest)

| Concern | Choice | Version |
| --- | --- | --- |
| Framework | React + React DOM | 19.x |
| Bundler/dev server | Vite | 7.x (`base: '/ui/'`) |
| Language | TypeScript | 5.x |
| Styling | Tailwind CSS (CSS-first) | 4.x via `@tailwindcss/vite` |
| Animation utilities | `tw-animate-css` | latest |
| Component primitives | shadcn/ui | latest (`components.json`) |
| Routing | react-router `HashRouter` | 7.x |
| Server state | TanStack Query | 5.x |
| Toasts | sonner | latest |
| Charts | Recharts | 3.x |
| Forms | react-hook-form + zod | rhf latest, zod 4.x |
| API types | openapi-typescript | latest |

### 1.2 Tailwind v4 migration

Adopt CSS-first Tailwind v4: add `@tailwindcss/vite` to the Vite plugin chain, import Tailwind from `src/index.css` with `@import "tailwindcss";` and `@import "tw-animate-css";`. Delete `tailwind.config.js`, `postcss.config.js`, and the `autoprefixer` and `postcss` devDependencies — v4 needs none of them. Design tokens are CSS variables under `:root` and `.dark`.

### 1.3 shadcn/ui setup

Add `components.json` configured for CSS-variable tokens and the `@/*` import alias (resolved in both `tsconfig.json` `paths` and `vite.config.ts` `resolve.alias` to `src/`). Dark mode is the default and is class-based: the root `<html>` carries the `dark` class on load (no toggle in v1). Generated primitives live in `src/components/ui/`.

### 1.4 Routing and mount

The SPA uses `HashRouter` so all client routes live under the `#` fragment, which means the server needs no catch-all rewrite — the static `/ui` mount serves `index.html` and Vite's hashed assets, and the browser resolves routes like `/ui/#/sources` entirely client-side. Vite `base` is `/ui/`. The dev server proxies `/api` to the backend.

### 1.5 Server state with TanStack Query v5

A single `QueryClient` configures: `staleTime` per query, polling via `refetchInterval` on live views (Overview, Ingestion, Triage), `refetchIntervalInBackground: false` plus a `visibilitychange` listener so polling pauses on a hidden tab, and `invalidateQueries` on every successful mutation (e.g. a source edit invalidates `['sources']` and `['stats','overview']`). Query keys are namespaced arrays (`['stats','overview']`, `['sources']`, `['jobs',{status,offset}]`, `['facts',{q}]`).

### 1.6 API typing and fetch wrapper

`npm run gen:api` runs `openapi-typescript http://127.0.0.1:8421/openapi.json -o src/lib/api-types.ts`; the generated file is committed. The existing thin fetch wrapper in `src/lib/api.ts` keeps `getToken()` and `authHeaders()` but the stale docstrings claiming "session cookie or query param" are replaced with the accurate contract:

```ts
// getToken(): GET /api/auth/token (the Token-Vending Endpoint) returns
// { token }. The endpoint is auth-exempt and same-origin; safe only under
// loopback/SSH-tunnel isolation. The token is held in module memory for the
// page session and attached as Authorization: Bearer to every /api call.
```

Every wrapper function reads the `X-Request-ID` (Correlation ID) response header and includes it in the thrown error so the UI can surface it.

### 1.7 Project structure

```
ui/src/
  pages/        # one file per route (Overview, Triage, ActionItems, Ingestion, Sources, Knowledge, Messenger, Settings)
  components/ui/ # shadcn primitives (generated)
  components/    # app components (AppSidebar, SourceForm, FactRow, ...)
  lib/          # api.ts (fetch wrapper), api-types.ts (generated), query-client.ts, format.ts
  hooks/        # useStatsOverview, useSources, useJobs, useFacts, ...
```

### 1.8 Shared primitives

| Primitive | Responsibility |
| --- | --- |
| `ErrorBoundary` | Catches render errors, renders the `error` state with the Correlation ID. |
| `Skeleton` | The `loading` state placeholder (shadcn skeleton). |
| `EmptyState` | The `empty` state: icon, message, optional CTA. |
| `StatCard` | Single labeled metric with optional trend/color (Overview cards). |
| `DataTable` | Sortable/paginated table wrapper over TanStack-driven rows (Sources, jobs). |
| `ChartCard` | Titled card wrapping a Recharts chart with its own loading/empty states. |
| `HealthBadge` | Renders **Source Health Status** / messenger reachability as a colored badge. |

### 1.9 UI State Taxonomy

Every data-bearing view implements the five **UI State Taxonomy** states with this mapping:

| State | Trigger | Render |
| --- | --- | --- |
| `loading` | query `isPending` | `Skeleton` |
| `error` | query `isError` (network/5xx) | `ErrorBoundary`/inline error + `X-Request-ID` |
| `empty` | success, zero rows | `EmptyState` (+ CTA where defined per page) |
| `unauthorized` | 401 from token or call | full-page "token unavailable; check tunnel/binding" |
| `degraded` | `available:false` / `configured:false` envelopes | informational panel (memory not enabled / no messenger), NOT `error` |

`dangerouslySetInnerHTML` is banned across the codebase (enforced by an ESLint `react/no-danger` rule); all content renders as React text nodes.

---

## Design Section 2 — Pages & Information Architecture

Sidebar navigation order is fixed: **Overview, Triage, Action Items, Ingestion, Sources, Knowledge, Messenger, Settings**.

### 2.1 Overview — route `/#/`

- Data sources: `GET /health`, `GET /api/stats/overview`, `GET /api/stats/ingestion-timeseries?days=14&bucket=day`, `GET /api/jobs?limit=10`.
- Six `StatCard`s: pending triage count; ingestion queue depth (`in_flight`); dead letters (badge turns red when `> 0`); active items; sources enabled/total with aggregate **Source Health Status**; messenger status (`HealthBadge`).
- Recharts: ingestion-timeseries (area chart, 14 days); items-by-priority (bar chart, P0–P3); items-by-source (donut chart); items-by-category (segmented bar over `action_item`/`meeting`/`plan_seed`/`informational`, fed by `stats.overview.items.by_category`).
- Recent jobs `DataTable` (10 rows): id, trigger, status, items_extracted, created_at.
- Conditional dead-letter alert banner shown above the cards only when dead letters `> 0`, linking to the Ingestion dead-letter table.
- Empty state: when `stats.overview` is all-zero, an `EmptyState` "No activity yet — add a source to begin" with a CTA to Sources.

### 2.2 Triage — route `/#/triage`

- Data source: `GET /api/triage/pending`.
- List of pending **Triage Card**s; each renders `card_content` summary, numbered `options` (1..n), and a free-text input.
- Respond via `POST /api/triage/respond` (`{card_id, choice}` for numbered; `{card_id, raw_text}` for free-text).
- Web-native confirmation flow: a free-text response that the server interprets as destructive returns `status: awaiting_confirmation` with an `explanation`; the UI renders a confirm/cancel dialog and on confirm calls `POST /api/triage/confirm`.
- Empty state: `EmptyState` "Inbox zero — no cards awaiting triage".

### 2.3 Action Items — route `/#/actions`

- Existing ActionList page preserved as-is against `GET /api/actions` with `markDone`/`changePriority`/`snooze` mutations migrated onto TanStack Query and the shared `DataTable`.

### 2.4 Ingestion — route `/#/ingestion`

- Data sources: `GET /api/stats/sources`, `GET /api/activity?limit=50`, `GET /api/jobs?status=&limit=&offset=`, `GET /api/stats/queue`, `GET /api/queue/dead-letter`.
- Per-source panels: adapter type, enabled flag, schedule, last-run time, qualified **Ingested Count**s (`items_stored`, `raw_enqueued`, `in_flight`), **Source Health Status** (`HealthBadge`), and a recent-items expander.
- Activity feed from `GET /api/activity`.
- Job history `DataTable` with a status filter (`queued/pending/running/completed/failed`) and offset pagination using `total`.
- Queue health panel from `GET /api/stats/queue`, plus a dead-letter `DataTable` with per-row retry (`POST /api/queue/dead-letter/{id}/retry`) and purge (`DELETE /api/queue/dead-letter/{id}`) actions.
- Empty state: "No ingestion runs yet" when `stats.sources` is empty.

### 2.5 Sources — route `/#/sources`

- Data sources: `GET /api/stats/sources`, `GET /api/sources/adapter-types`, `GET /api/connections`.
- `DataTable` columns: `adapter_type`, id/label, `enabled` `Switch`, schedule (human-readable + cron in a tooltip), last_run (relative), `items_ingested` (qualified `items_stored`), **Source Health Status** (`HealthBadge`), kebab actions (Edit, Poll-now, Enable/Disable, Delete).
- Two-step add-source form:
  - Step 1: pick `adapter_type` from `{github, email, calendar, chat}`.
  - Step 2: type-specific fields via react-hook-form + a zod discriminated union (one variant per `adapter_type`) that mirrors each provider's `ProviderConfig`, with the schema sourced from `GET /api/sources/adapter-types` `model_json_schema`.
- Connection picker for Google adapters: a select populated from `GET /api/connections` names; adapter types whose `requires_connection` is true are disabled when no matching connection exists.
- Schedule controls: cron presets dropdown, an "advanced" custom-cron text field, and a next-run preview computed from the cron.
- Secrets UX: the form NEVER accepts a typed secret — a Google adapter references a connection by name; a `github` adapter shows an informational note that it uses ambient `gh` auth.
- Mutation semantics: pessimistic create/edit (await server, then invalidate); optimistic enable/disable with rollback on failure; field-level 422 errors mapped to the offending form fields.
- `adapter_type` is immutable on edit (rendered read-only).
- On a successful restart-free hot-add, a sonner success toast "Source added and polling live".
- Empty state: `EmptyState` with an "Add your first source" CTA opening Step 1.

### 2.6 Messenger — route `/#/messenger`

- Read view from `GET /api/messenger?check=true`: type, class, allowlisted config (`space_id`, `timeout_seconds`), reachability `HealthBadge`. `service_account_key_path` is never shown.
- Edit config form: `PATCH /api/messenger` writes YAML via **Config Write-Back** and hot-swaps the provider.
- `degraded` "no messenger" info state when `configured:false`, showing the current pending triage count (from `GET /api/triage/pending`) so the user sees what is queued but unsent.

### 2.7 Knowledge — route `/#/knowledge`

- Data source: `GET /api/memory/facts` returning the envelope `{available, memory_type, facts:[{id,content,source,timestamp}]}`.
- Facts list with text search and group-by-source.
- Three distinct empty/degraded states:

| Condition | Envelope | Render |
| --- | --- | --- |
| Noop memory | `available:false, memory_type:"noop"` | `degraded` "Memory layer not enabled" |
| Configured but unreachable | `available:false, memory_type:"zep"` | `degraded` "Memory service unreachable" + `X-Request-ID` |
| Configured, no facts | `available:true, facts:[]` | `empty` "No preference facts learned yet" |

- **Fact Curation** controls: per-fact edit and delete, each behind a confirm dialog, calling `PATCH /api/memory/facts/{id}` and `DELETE /api/memory/facts/{id}`.
- An entities-count `StatCard` (scalar only) reads the `total` field from `GET /api/memory/entities` (best-effort; shows `—` when memory is unavailable) and links to a future entities view; v1 shows flat facts only and renders no entity/relationship graph.

### 2.8 Settings — route `/#/settings`

- Read-only system information page (no writes in v1; provider edits live on the Sources and Messenger pages).
- Data sources: `GET /health`, `GET /api/debug/config` (already secret-redacted).
- Renders: app version and config version (from `/health`); storage and connection component health (`HealthBadge` per component); a read-only view of the redacted `pipeline`, `scheduler`, `retention`, and `alerting` config sections from `GET /api/debug/config`.
- `degraded` state when `/health` returns 503 (storage down): show the banner and the last-known component statuses.
- Empty state: not applicable (config sections always present); on `GET /api/debug/config` failure, render the `error` state with the `X-Request-ID`.

---

## Design Section 3 — Backend: Stats & Aggregation API

### 3.1 Endpoints

```
GET /api/stats/overview        -> counts: pending_triage, in_flight, dead_letters,
                                   active_items, sources_enabled, sources_total
GET /api/stats/sources         -> per-source: adapter_type, enabled, schedule, last_run,
                                   items_stored, raw_enqueued, in_flight, health_status
GET /api/stats/queue           -> queued, processing, dead_letter counts + oldest age
GET /api/stats/ingestion-timeseries?days=14&bucket=day  -> [{bucket_ts, raw_enqueued}]
GET /api/jobs?limit=&offset=&status=  -> {jobs:[...], total}
GET /api/activity?limit=        -> recent activity rows (promoted out of /api/debug/pipeline)
```

The **Stats Endpoint** returns pre-computed aggregates only (`COUNT ... GROUP BY`); it never returns entity rows (those stay on `/api/items`, `/api/jobs`). `GET /api/activity` promotes the recent-activity slice out of `/api/debug/pipeline` into a first-class endpoint.

### 3.2 New repository methods

| Repository | Method | Returns |
| --- | --- | --- |
| `ItemStore` | `count_by_status()` | `dict[str,int]` |
| `ItemStore` | `count_by_priority()` | `dict[str,int]` |
| `ItemStore` | `count_by_category()` | `dict[str,int]` |
| `ItemStore` | `count_by_source()` | `dict[str,int]` (items_stored) |
| `IngestionQueueStore` | `count_by_status()` | `dict[str,int]` |
| `IngestionQueueStore` | `count_by_source()` | `dict[str,int]` (raw_enqueued + in_flight) |
| `IngestionQueueStore` | `count_dead_letters()` | `int` (COUNT, not full scan) |
| `JobStore` | `list_jobs(limit, offset, status)` | `list[PipelineJob]` |
| `JobStore` | `count(status)` | `int` |
| `IngestionRunStore` | `timeseries(days, bucket)` | `list[(ts,int)]` via `date_trunc` |

The ingestion time series uses `date_trunc(:bucket, started_at)` `GROUP BY` over `ingestion_runs`.

### 3.3 Indexes

```sql
CREATE INDEX ix_items_source_status        ON items (source_type, status);
CREATE INDEX ix_ingestion_queue_status     ON ingestion_queue (status);
```

### 3.4 Bug fixes folded in

- `/health` uses `get_depth()` while `_alert_check` uses `queue_depth()`; standardize both call sites on a single `IngestionQueueStore.queue_depth()` method and remove `get_depth`.
- Replace the dead-letter full-scan (`len(get_dead_letters())`) at the `/health` and Overview call sites with the new `count_dead_letters()` COUNT query.
- All API responses qualify the **Ingested Count** as `raw_enqueued` / `items_stored` / `in_flight`; the bare term never appears in a field name.

---

## Design Section 4 — Backend: `ingestion_runs` table & IngestionRunStore

### 4.1 Schema

```sql
CREATE TABLE ingestion_runs (
    id           UUID PRIMARY KEY,
    source_id    TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL,          -- running | success | error
    raw_enqueued INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);
CREATE INDEX ix_ingestion_runs_source_started ON ingestion_runs (source_id, started_at DESC);
```

Each row is one **Ingestion Run** (per source poll, scheduled or manual). An Alembic migration creates the table and index.

### 4.2 IngestionRunStore interface

```python
class IngestionRunStore(ABC):
    async def start_run(self, source_id: str) -> str: ...      # inserts status=running, returns id
    async def finish_run(self, run_id: str, raw_enqueued: int) -> None: ...  # status=success
    async def error_run(self, run_id: str, error: str) -> None: ...          # status=error
    async def latest_for_source(self, source_id: str) -> IngestionRun | None: ...
    async def timeseries(self, days: int, bucket: str) -> list[tuple[datetime, int]]: ...
    async def delete_older_than(self, days: int) -> int: ...
```

### 4.3 Wiring

`_poll_one_source` calls `start_run` at entry, `finish_run` on success with the count of enqueued raw items, and `error_run` on exception. A new `RetentionConfig.ingestion_runs_days` (default 30) drives `delete_older_than`, invoked from `run_retention_cleanup`. **Ingestion Run** rows back **Source Health Status**, per-source qualified counts, and the time series.

---

## Design Section 5 — Backend: Source Management API + Config Write-Back + Targeted Hot-Reload

### 5.1 Endpoints

```
POST   /api/sources              -> create (body: {adapter_type, config, schedule, enabled})
PATCH  /api/sources/{id}         -> edit (adapter_type immutable; 422 on attempt to change)
DELETE /api/sources/{id}         -> remove
POST   /api/sources/{id}/poll    -> manual poll (trigger=MANUAL)
GET    /api/sources/adapter-types  -> [{adapter_type, model_json_schema, requires_connection}]
GET    /api/connections          -> [{name, healthy}]   (names + health, never secrets)
```

### 5.2 Adapter-type allowlist (import-gadget guard)

The API accepts only a short `adapter_type` name (`github`, `email`, `calendar`, `chat`); the server maps it to a class path via a fixed server-side allowlist dict. A raw dotted class path is never accepted from the client. The mapped class's `ProviderConfig` validates the submitted `config`; field errors return 422.

```python
ADAPTER_ALLOWLIST = {
    "github":   "workbench.providers.source.github.GitHubSourceAdapter",
    "email":    "workbench.providers.source.gmail.GmailAdapter",
    "calendar": "workbench.providers.source.gcalendar.GCalendarAdapter",
    "chat":     "workbench.providers.source.gchat.GChatAdapter",
}
```

### 5.3 Config Write-Back

A UI-initiated source change is persisted by **Config Write-Back**: a ruamel.yaml round-trip loads `config.yml`, edits only the `sources:` node for the affected source, and writes atomically (temp file + `os.replace`). `${oc.env:...}` interpolation strings, comments, and formatting are preserved. The resolved OmegaConf container is never re-serialized (that would bake plaintext secrets into the file). A stable `source.id` is written back into the YAML; this is a config-schema change, so the **Config File** `version` minor is bumped. The `source_configs` DB table is deprecated as a config store — `config.yml` is the single source of truth.

### 5.4 Targeted Hot-Reload

After a successful write, **Targeted Hot-Reload** applies the change live under an `asyncio.Lock` with the sequence: **validate -> instantiate -> write YAML -> swap**. The sources list in `app.state` is replaced copy-on-write; the per-source **Source Job** is added/rescheduled/removed accordingly (see Section 6). A change that requires a connection not currently defined is rejected (connections remain YAML-only + restart). Secrets never enter the DB or YAML values.

### 5.5 Connections read endpoint

`GET /api/connections` returns each connection's `name` and `Connection.is_healthy()` result — no `service_account_key_path`, tokens, or DSN.

---

## Design Section 6 — Backend: Per-source Cron Scheduler + Watermark redesign

### 6.1 Source Jobs

The single global `poll_sources` interval job is replaced by one **Source Job** per enabled source: an APScheduler `CronTrigger` with id `poll_source:{source_id}`, cron derived from `SourceConfig.schedule` via `CronTrigger.from_crontab`, `max_instances=1`, `coalesce=True`, timezone from `config.logging.timezone`. `poll_interval_minutes` is demoted to driving only the `alert_check` job.

### 6.2 Runtime job management

On source add/edit/disable/delete (via Section 5 endpoints), the scheduler adds, reschedules, or removes the corresponding **Source Job** at runtime within the hot-reload sequence.

### 6.3 Shared poll function

```python
async def _poll_one_source(self, source_id: str, trigger: JobTrigger) -> None:
    # acquires a per-source asyncio.Lock; used by both Source Job (POLL) and manual (MANUAL)
```

`_poll_one_source` is shared by scheduled and manual polls, guarded by a per-`source_id` `asyncio.Lock`, and owns the **Ingestion Run** start/finish/error hooks from Section 4.

### 6.4 Watermark redesign

The poll cursor moves from `source_last_polled:{adapter_type}` to the `source_id`-keyed **Watermark** `source_last_polled:{source_id}`, stored in `stores.config` and passed as `since=` to `SourceAdapter.poll()`. A one-time, non-destructive migration copies any existing `source_last_polled:{adapter_type}` value to the matching `source_id` key (the old key is left in place, not deleted).

### 6.5 Validation and startup

Cron strings are validated at the API boundary via `CronTrigger.from_crontab` (invalid cron -> 422). At startup, first-run times are staggered across sources to avoid a thundering herd.

---

## Design Section 7 — Backend: Messenger Info/Edit API

### 7.1 Endpoints

```
GET   /api/messenger[?check=true]  -> 200 always
PATCH /api/messenger               -> edit via Config Write-Back + hot-swap
```

`GET /api/messenger` returns `{configured, type, class, config:{...allowlisted...}}`; when `?check=true` it adds `{reachable, checked_at}`. `configured` is `false` when the messenger provider is `None` (degraded, not an error). The allowlisted config exposes `space_id` and `timeout_seconds` only — never `service_account_key_path`.

### 7.2 Edit + hot-swap

`PATCH /api/messenger` runs **Config Write-Back** on the `messenger:` node then **Targeted Hot-Reload**, rebinding `app.state.messenger`, `scheduler.messenger`, and `alert_manager.messenger` to the new instance under the same `asyncio.Lock`.

---

## Design Section 8 — Backend: Facts read + Fact Curation

### 8.1 Facts read envelope

`GET /api/memory/facts` returns 200 always with:

```json
{
  "available": true,
  "memory_type": "zep",
  "facts": [
    {"id": "fact-uuid", "content": "user prioritizes blocked PRs", "source": "interaction", "timestamp": "2026-06-01T00:00:00Z"}
  ]
}
```

`available` is `false` (degraded) for `NoopMemoryLayer` or an unreachable service. The `Fact` model gains `id: str` and `timestamp: datetime | None`; the memory provider's `http.py` is fixed to populate `timestamp` (currently dropped).

### 8.2 Fact Curation endpoints

```
DELETE /api/memory/facts/{id}  -> MemoryLayer.delete_fact(id)
PATCH  /api/memory/facts/{id}  -> MemoryLayer.update_fact(id, content)
```

Both return 501 under `NoopMemoryLayer`. **Fact Curation** is end-to-end: UI -> endpoint -> `MemoryLayer` method -> memory service.

### 8.3 MemoryLayer interface additions

```python
class MemoryLayer(ABC):
    async def delete_fact(self, fact_id: str) -> None: ...   # Noop raises NotImplemented -> 501
    async def update_fact(self, fact_id: str, content: str) -> None: ...
    async def list_facts(self) -> list[Fact]: ...            # list-all contract (ids + timestamps)
```

### 8.4 Memory service (workbench-meta)

The Graphiti-backed memory service in workbench-meta adds `DELETE /facts/{id}` and `PATCH /facts/{id}`, each writing a tombstone / negative-preference so a curated fact is not re-synthesized from the **Interaction Log**, plus the list-all-facts contract. **Fact Curation** is recorded via ordinary structured app logging — it is deliberately NOT written to the **Interaction Log**.

---

## Design Section 9 — Backend: Triage web-respond

### 9.1 Numbered + free-text respond

`POST /api/triage/respond` is reused for both numbered (`choice`) and free-text (`raw_text`) web responses. A 409 guard rejects a card already `responded` or `expired` before any processing.

### 9.2 Web confirmation flow

A free-text response interpreted as destructive sets the card to `awaiting_confirmation`, stores the pending `InterpretedResponse` on `card_content`, and returns `status: awaiting_confirmation` with the `explanation`. The UI confirms via `POST /api/triage/confirm` (`{card_id, confirm: bool}`), which executes the stored destructive actions on confirm or returns the card to `sent` on cancel — the web mirror of the messenger `_handle_confirmation` path.

### 9.3 Interaction-log audit gap

Every web response creates an `InteractionEntry`. The early-return branches in `_execute_interpreted_response` (destructive-pending and defer) currently skip logging; this gap is closed so those branches also append an `InteractionEntry` capturing the interpreted intent.

### 9.4 Dead-letter actions

The existing single-item `POST /api/queue/dead-letter/{id}/retry` and `DELETE /api/queue/dead-letter/{id}` endpoints are reused by the Ingestion page; no bulk variant is added.

---

## Design Section 10 — Security, Auth & Redaction

### 10.1 Redaction Rule

`_redact_secrets` is promoted from `api/debug.py` to `workbench/redaction.py` as the shared `redact_secrets()` **Redaction Rule**: a key-name denylist regex (`token|key|secret|password|dsn|credential|service_account|...`) plus an explicit field denylist. Every read endpoint serializing config-derived data applies it; new endpoints (`/api/messenger`, `/api/connections`, `/api/sources/adapter-types`, `/api/stats/sources`) prefer allowlist-on-output, returning only named safe fields. `service_account_key_path`, tokens, and the DSN are never exposed.

### 10.2 Auth

Bearer auth guards every endpoint except `/health` and the **Token-Vending Endpoint** `GET /api/auth/token`. The token endpoint is safe only under loopback/SSH-tunnel isolation; the server should bind `127.0.0.1`/`::1`, and the SSH-tunnel boundary is documented as the security perimeter. No CORS is configured — the SPA is same-origin under `/ui`.

### 10.3 Boundary validation

Cron strings validate via `CronTrigger.from_crontab` and source/messenger configs validate against the provider `ProviderConfig` at the API boundary. The `adapter_type` allowlist (Section 5.2) is the import-gadget guard — no client-supplied class path is ever imported.

---

## Design Section 11 — Testing & Hardening

### 11.1 Backend (pytest)

- Auth: every new endpoint returns 401 without a token and 200 with one; the **Token-Vending Endpoint** is reachable unauthenticated.
- Redaction regression: parametrized over seeded fake secrets (token, key, `service_account_key_path`, DSN) asserting none appear in any read response.
- Validation: malformed `config`/cron returns 422 with field-level errors; `adapter_type` change on PATCH returns 422.
- Aggregation correctness: seeded rows produce exact `count_by_*` and timeseries results.
- Concurrency: a second response to an already-responded card returns 409.
- Config Write-Back: round-trip preserves `${oc.env:...}` interpolations, comments, and unrelated nodes; write is atomic.

### 11.2 Frontend (Vitest + React Testing Library + MSW)

- Five **UI State Taxonomy** states rendered per page via MSW fixtures.
- Token bootstrap path (token present / 401).
- Mutations: happy path and failure-with-rollback (optimistic enable/disable).

### 11.3 Accessibility

Keyboard navigation across the sidebar and tables; modal focus trap with focus return on close; `aria-label` on every icon-only button; dark-mode contrast verified for the P0–P3 priority badges; visible focus rings on all interactive elements.

### 11.4 Audit logging

Every config mutation (source CRUD, messenger edit) emits a structured app-log audit record carrying the request's **Correlation ID**.

---

## File Changes

### Frontend (new)

| File | Purpose |
| --- | --- |
| `ui/components.json` | shadcn/ui config (CSS vars, `@/*` alias). |
| `ui/src/lib/api-types.ts` | Generated `openapi-typescript` types (committed). |
| `ui/src/lib/query-client.ts` | TanStack `QueryClient` + visibility pause. |
| `ui/src/pages/Overview.tsx` | Overview page. |
| `ui/src/pages/Triage.tsx` | Triage page. |
| `ui/src/pages/Ingestion.tsx` | Ingestion page. |
| `ui/src/pages/Sources.tsx` | Sources page. |
| `ui/src/pages/Knowledge.tsx` | Knowledge / Fact Curation page. |
| `ui/src/pages/Messenger.tsx` | Messenger info/edit page. |
| `ui/src/pages/Settings.tsx` | Settings page. |
| `ui/src/components/AppSidebar.tsx` | Fixed-order sidebar nav. |
| `ui/src/components/SourceForm.tsx` | Two-step add/edit source form. |
| `ui/src/components/{ErrorBoundary,EmptyState,StatCard,DataTable,ChartCard,HealthBadge}.tsx` | Shared primitives. |
| `ui/src/components/ui/*` | Generated shadcn primitives. |
| `ui/src/hooks/*` | Query hooks. |

### Frontend (modified)

| File | Change |
| --- | --- |
| `ui/package.json` | React 19, Vite 7, Tailwind v4 (`@tailwindcss/vite`, `tw-animate-css`), react-router 7, TanStack Query v5, Recharts 3, zod 4, rhf, sonner, openapi-typescript; drop `autoprefixer`/`postcss`; add `gen:api` script. |
| `ui/vite.config.ts` | `base:'/ui/'`, `@tailwindcss/vite` plugin, `@/*` alias, `/api` dev proxy. |
| `ui/tsconfig.json` | `paths` for `@/*`. |
| `ui/src/lib/api.ts` | Move from `ui/src/api.ts`; fix token docstring; surface `X-Request-ID`. |
| `ui/src/index.css` | Tailwind v4 CSS-first imports + token vars + `.dark`. |
| `ui/tailwind.config.js`, `ui/postcss.config.js` | Deleted. |

### Backend (new)

| File | Purpose |
| --- | --- |
| `src/workbench/api/stats.py` | `GET /api/stats/*`. |
| `src/workbench/api/activity.py` | `GET /api/activity`. |
| `src/workbench/api/messenger.py` | `GET/PATCH /api/messenger`. |
| `src/workbench/api/connections.py` | `GET /api/connections`. |
| `src/workbench/redaction.py` | Shared `redact_secrets()` Redaction Rule. |
| `src/workbench/storage/ingestion_runs.py` | `IngestionRunStore` interface + PG impl. |
| `src/workbench/config_writeback.py` | ruamel round-trip Config Write-Back. |
| `src/workbench/migrations/versions/*_ingestion_runs.py` | `ingestion_runs` table. |
| `src/workbench/migrations/versions/*_stats_indexes.py` | items/ingestion_queue indexes. |

### Backend (modified)

| File | Change |
| --- | --- |
| `src/workbench/api/sources.py` | Add POST/PATCH(full)/DELETE/poll/adapter-types; allowlist + write-back + hot-reload. |
| `src/workbench/api/memory.py` | Envelope response; add DELETE/PATCH curation. |
| `src/workbench/api/triage.py` | 409 guard; `POST /api/triage/confirm`; audit-gap fix. |
| `src/workbench/api/health.py` | Use `queue_depth()` + `count_dead_letters()`. |
| `src/workbench/api/jobs.py` | `limit/offset/status` + `total`. |
| `src/workbench/api/debug.py` | Move `_redact_secrets` to `redaction.py`; promote activity slice out. |
| `src/workbench/pipeline/scheduler.py` | Per-source Source Jobs; `_poll_one_source`; watermark by `source_id`; Ingestion Run hooks; runtime job mgmt. |
| `src/workbench/models.py` | `Fact.id`, `Fact.timestamp: datetime|None`; `IngestionRun` model. |
| `src/workbench/memory/base.py` | `delete_fact`/`update_fact`/`list_facts`. |
| `src/workbench/storage/base.py` | Add `IngestionRunStore` to `Stores`; new count/list methods on Item/IngestionQueue/Job stores. |
| `src/workbench/config.py` | `RetentionConfig.ingestion_runs_days`; config `version` bump. |
| `src/workbench/main.py` | Mount static `/ui`; register new routers; hot-reload `asyncio.Lock` on `app.state`. |

### Docs (workbench-meta)

| File | Change |
| --- | --- |
| memory-service docs | `DELETE/PATCH /facts/{id}` with tombstone/negative-preference + list-all-facts contract. |

---

## Verification

This feature is done when:

1. Navigating to `/ui` over the SSH tunnel loads the SPA, fetches a token from `GET /api/auth/token`, and renders Overview without a manual token paste.
2. `GET /api/stats/overview` returns the six counts and `GET /api/stats/ingestion-timeseries?days=14&bucket=day` returns 14 buckets, both computed by `COUNT ... GROUP BY` repository methods (verified against seeded rows).
3. `GET /health` and `_alert_check` both call `queue_depth()`, and dead-letter counts come from `count_dead_letters()` (no full scan), verified by query-log assertion in a test.
4. Polling a source inserts one `ingestion_runs` row (`running` -> `success`/`error`) and the Ingestion page shows the source's `items_stored`, `raw_enqueued`, and `in_flight` distinctly.
5. `POST /api/sources` with `adapter_type:"github"` writes a `sources:` node to `config.yml` preserving `${oc.env:...}` and comments, adds a `poll_source:{id}` Source Job, and the source polls without a restart (success toast shown).
6. `PATCH /api/sources/{id}` rejects an `adapter_type` change with 422 and a bad cron with 422.
7. `DELETE /api/sources/{id}` removes the `sources:` node and the Source Job.
8. Each enabled source has exactly one `CronTrigger` job `poll_source:{source_id}` with `max_instances=1, coalesce=True`; no global `poll_sources` job exists.
9. The watermark is read/written at `source_last_polled:{source_id}`, and an existing `:{adapter_type}` value is copied (not deleted) on first run.
10. `GET /api/messenger?check=true` returns `configured/type/class/config{space_id,timeout_seconds}/reachable/checked_at` and never `service_account_key_path`; `PATCH /api/messenger` rebinds `scheduler.messenger` and `alert_manager.messenger`.
11. `GET /api/memory/facts` returns the `{available, memory_type, facts:[{id,content,source,timestamp}]}` envelope with populated timestamps; `DELETE`/`PATCH /api/memory/facts/{id}` return 501 under `NoopMemoryLayer` and succeed against the memory service.
12. `POST /api/triage/respond` on a `responded` card returns 409; a destructive free-text response returns `awaiting_confirmation` and `POST /api/triage/confirm` executes or cancels it; both paths append an `InteractionEntry`.
13. A redaction regression test seeded with fake secrets confirms no token/key/DSN/`service_account_key_path` appears in any read response.
14. Every data-bearing page renders all five UI State Taxonomy states under MSW fixtures, and optimistic enable/disable rolls back on a forced failure.
15. `npm run gen:api` regenerates `src/lib/api-types.ts` cleanly against `/openapi.json`, and `tailwind.config.js`/`postcss.config.js`/`autoprefixer` are absent.

## Resolved Questions

1. **UI client model:** -> The Management Dashboard is a pure HTTP client; all reads/writes go through `/api`, never direct storage. Keeps the storage abstraction single-entry and matches the existing plugin contract.
2. **Frontend stack:** -> React 19 + Vite 7 + TypeScript + Tailwind v4 (CSS-first) + shadcn/ui, dark-by-default, sidebar nav, Recharts 3. Modern, token-themeable, chart-capable, low-ceremony.
3. **Product name:** -> "Workbench" (the surface is the **Management Dashboard**, distinct from the messenger Morning Briefing). Avoids the overloaded bare "dashboard".
4. **Auth:** -> Bearer auth on all endpoints except `/health` and the auth-exempt **Token-Vending Endpoint** `GET /api/auth/token`. Single-user loopback tool; the tunnel is the perimeter.
5. **Serving + routing:** -> Static `/ui` mount, Vite `base:'/ui/'`, `HashRouter` (no server catch-all), `/api` dev proxy, reached over SSH tunnel. Hash routing removes server-side rewrite complexity.
6. **Scope:** -> Full-stack feature (frontend SPA + backend stats/CRUD/curation/triage APIs). The UI value depends on the new aggregation and write paths.
7. **Write capabilities:** -> Full management writes — sources CRUD + poll-now, dead-letter retry/purge, triage respond/confirm, messenger edit, Fact Curation. Decisive "do it now" posture; avoids a later read-only-to-read-write migration.
8. **Tenancy:** -> Single-user; no workspace scoping anywhere. Matches the dropped Workspace concept.
9. **Storage:** -> PostgreSQL behind the repository pattern with Alembic migrations for the new table and indexes. Consistent with the existing backend.
10. **Library versions:** -> Latest across the board (Tailwind v4, React 19, Vite 7, react-router 7 HashRouter, TanStack Query v5, Recharts 3, Zod 4, openapi-typescript); migrate the existing `ui/` scaffold off React 18 / Vite 6 / Tailwind v3. Avoids near-term churn.
11. **Config persistence + reload:** -> **Config Write-Back** to `config.yml` via ruamel round-trip (preserve interpolations/comments, atomic temp + `os.replace`) plus **Targeted Hot-Reload** (validate -> instantiate -> write -> swap under `asyncio.Lock`); YAML is the single source of truth and `source_configs` is deprecated as a config store. Keeps secrets out of the DB and avoids restarts for source/messenger edits.
12. **Scheduler + watermark:** -> One **Source Job** (`CronTrigger`) per enabled source plus `source_id`-keyed **Watermark**s, with a non-destructive migration from `:{adapter_type}` keys. Enables per-source schedules, manual poll, and accurate cursors.
13. **Fact curation:** -> End-to-end edit/delete including memory-service `DELETE/PATCH /facts/{id}` with tombstone/negative-preference and a service-assigned `Fact.id`; 501 under `NoopMemoryLayer`. Prevents deleted facts from being re-synthesized from the Interaction Log.
14. **Web triage:** -> Reuse `POST /api/triage/respond` for numbered + free-text, add a web confirmation flow via `POST /api/triage/confirm`, a 409 double-response guard, and close the interaction-log audit gap on early-return branches. Mirrors the messenger path web-natively.

## Out of Scope

- Connection creation / OAuth via the UI — connections stay `config.yml`-only and require a restart.
- Entity / relationship graph view — v1 surfaces flat **Preference Fact**s only.
- Bulk dead-letter actions — retry/purge are single-item only.
- Multi-user / workspace isolation.
- Hot-adding non-Google new connections — only sources referencing an already-defined connection hot-add.
- Per-fact confidence scores or categories.
