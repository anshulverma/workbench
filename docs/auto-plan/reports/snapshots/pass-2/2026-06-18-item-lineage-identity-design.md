# Item Lineage & Stable Identity — Design

Date: 2026-06-18
Status: Approved (pending spec review)
Repo: `workbench` (base package). Meta plugin `workbench-meta` inherits unchanged.

## Goal

Guarantee that every `Item` has a unique identity that is assigned the moment it
enters the system and remains stable and traceable for its entire lifecycle —
including the LLM-heavy pre-persist stages and the action queue. Make the lineage
between a source artifact, its extracted items, and their actions explicit and
navigable via hierarchical IDs (`#123`, `#123.1`, `#123.1.2`).

## Background — current reality

- `Item.id` is a Postgres autoincrement `BIGINT`, assigned at `save_item`
  (migrations `010_integer_ids_items_cards` / `011_integer_ids_remaining` moved
  from UUID strings to integer surrogate keys).
- Once assigned, the id is stable across status changes and is referenced by FKs
  (`parent_item_id`, `triage_cards.item_id`).
- Four gaps versus the goal:
  1. **Late birth.** No `Item.id` exists during `enqueue → extract → score →
     filter`; the thing is tracked only by `RawItem.id` (string) and the natural
     key `(source_type, source_id)`. LLM calls in this window reference items by
     free-text summaries, not a stable id.
  2. **Action items are new items.** A triage response creates a *child* `Item`
     with a fresh id + `parent_item_id`; the id "changes" entering the action
     queue.
  3. **One raw thing → many items.** `extract_items` can split one ingested
     `RawItem` into several top-level `Item`s.
  4. **No DB-level uniqueness** on `(source_type, source_id)`; dedup relies on a
     `processed`-store check, so a race/reset could mint duplicate items for one
     real-world thing.

## Decisions

### D1 — Hierarchical identity representation: materialized path (Option A)

Keep the integer surrogate PK. Encode lineage with two added columns plus the
existing `parent_item_id`:

- `seq SMALLINT NULL` — 1-based index among siblings sharing a parent
  (`NULL` for roots).
- `path TEXT NOT NULL` — full lineage string: `"123"`, `"123.1"`, `"123.1.2"`.
  - Root: `path = str(id)` (root segment is the global autoincrement id).
  - Child: `path = f"{parent.path}.{seq}"`.

Rejected alternatives:
- **Path string as PK** — reverses the recent integer-id migration, breaks all
  int FKs. Not worth it.
- **`ltree` / closure table** — built for large, deep, hot trees and for
  reparenting. Here trees are shallow and small, the dominant access is
  point-lookup-by-path and one-level children, and identity is immutable (no
  reparenting), which removes a closure table's main advantage. Subtree queries
  are served by an indexed `path LIKE '123.%'` range scan. `ltree` would also add
  a Postgres extension dependency. Can be layered on later as a derived index if
  the workload ever grows into it.

Subtree-prefix safety: a subtree scan that wants the descendants of `#123` uses
`path = '123' OR path LIKE '123.%'` (the literal `'123.'` dot guard), NOT
`path LIKE '123%'` — the latter would wrongly match `1234`, `12300`, etc. The
plan's navigation queries avoid `LIKE` entirely (`get_children` filters on
`parent_item_id`; `get_ancestors` matches the exact set of prefix segments via
`path = ANY(...)`), so no prefix-collision can occur there; any future subtree
analytics that does use `LIKE` MUST use the `'123.'` dotted guard plus the exact
`'123'` match.

### D2 — Three-tier tree

| Depth | What it is | Born when | Status |
|---|---|---|---|
| 0 — root `#123` | the ingested source artifact (diff / task / doc) | at ingestion (`enqueue`) | `INGESTED → EXTRACTED` |
| 1 — `#123.1` | each extracted item | at extraction | verdict → `ACTIVE` / `DROPPED` / `PENDING_TRIAGE` |
| 2+ — `#123.1.2` | actions from triage responses (or deeper extraction) | at action creation | `ACTIVE` |

The auto_include / auto_drop / triage **verdicts move onto the depth-1 extracted
children**. The root is a stable container that holds source identity and the
ingestion-stage funnel log. Trees are arbitrary depth: a deeper extraction nests
further (`#123.1` → `#123.1.1`).

The root and all of its descendants share the same `(source_type, source_id)`
natural key (children are built with `source_id = raw_item.id`). Identity is
disambiguated by `parent_item_id`: the **root is the unique row with
`parent_item_id IS NULL`** for a given `(source_type, source_id)` (enforced by
the partial unique index in the Data model section). Any lookup that must return
"the source artifact" therefore filters `parent_item_id IS NULL` (see D3).

### D3 — Birth at ingestion

`PipelineEngine.enqueue` (which already dedupes and creates the job/queue entry)
also creates the root `Item` row with status `INGESTED`, so the autoincrement
assigns `#123` immediately. The root carries the **source snapshot** in
`raw_data` as a `RawItem`-shaped dict (`{"raw_text": <source json>, ...}`), so
the root is the row the scheduler's change-detector diffs against on re-poll
(`scheduler._parse_raw` reads `raw_data["raw_text"]`).

`process_raw_item` re-resolves the root at extraction time via
`get_item_by_source_id(source_type, source_id)`. Because root and children share
`(source_type, source_id)`, `get_item_by_source_id` is changed to resolve the
**root only** — it adds `AND parent_item_id IS NULL` (matching the partial unique
key). This is also the row the scheduler polling loop
(`scheduler.py` change-detection) resolves and updates via `update_raw_data`, so
no new field is added to `IngestionQueueEntry`. The same id then exists for the
entire journey. `LLMCallContext` (today a frozen dataclass with only
`origin`/`purpose`/`stage`) gains an optional `item_paths: tuple[str, ...] = ()`
field; the path ids of the items a call is for are stamped there, plumbed through
`PlugboardCallRecord.context`, and preferred by `runtime/app.py` over the
free-text `subcalls[].item` values when present — so `LlmCallRecord.items`
records `123`, `123.1` (closes gap #1; the LLM Infra `items` column becomes real
lineage references).

Feed isolation: the `INGESTED`/`EXTRACTED` root statuses are NOT among the
verdict statuses the active/triage feeds query (`get_items` filters by an exact
status; the active feed asks for `ACTIVE`, triage for `PENDING_TRIAGE`), so roots
never surface in those feeds. `get_active_by_source` (used only by
`_detect_disappeared` for poll-completeness archival) does return roots, but a
root's `source_id` is always present in a complete poll's `seen_ids`, so a root
is never wrongly archived.

### D4 — Immutability rules

- Sequences are **append-only and never renumbered.** Deleting `#123.1` leaves a
  gap; `#123.2` stays `#123.2`. No id is ever reused or reassigned.
- `path` is **immutable after creation** — only ever set on insert; no update
  path in the code.

## Data model

Schema changes to `items`:
- Add `seq SMALLINT NULL`, `path TEXT NOT NULL`.
- Add enum values `INGESTED`, `EXTRACTED` to `ItemStatus`.
- Constraints:
  - `UNIQUE(path)`
  - `UNIQUE(parent_item_id, seq)` — concurrent-sibling race backstop.
  - Partial `UNIQUE(source_type, source_id) WHERE parent_item_id IS NULL` —
    closes gap #4 (never two roots for one source thing) and is the key that
    makes the root the unique `parent_item_id IS NULL` row per source (D2/D3).
- Indexes: B-tree on `path` with `text_pattern_ops` (indexed `LIKE '123.%'`
  subtree scans); B-tree on `parent_item_id`.

### Allocation seam

All path/seq logic lives in one pair of store methods so the denormalized `path`
never leaks into call sites:
- `create_root(...)` — insert, `RETURNING id`, then set `path = str(id)`.
- `allocate_child(parent, ...)` — `seq = COALESCE(MAX(seq),0)+1` over siblings
  within the insert txn under `pg_advisory_xact_lock(parent.id)`;
  `path = f"{parent.path}.{seq}"`; on `UNIQUE(parent_item_id, seq)` conflict,
  retry.

### Source-id resolution

`get_item_by_source_id(source_type, source_id)` adds `AND parent_item_id IS NULL`
so it resolves the root (the source artifact), not a child. Both call sites rely
on this: extraction re-resolves the root to nest children under it, and the
scheduler change-detection loop resolves the root to diff/update its source
snapshot. `get_active_by_source` keeps its `status NOT IN ('archived','done')`
filter; roots it returns are protected from archival as described in D3.

## Pipeline / scheduler changes

- `pipeline/engine.py`: create root at `enqueue` (`INGESTED`) carrying the source
  snapshot in `raw_data`; on extraction create depth-1 children via
  `allocate_child` and apply verdicts to them (`EXTRACTED` for the root once
  children exist).
- `pipeline/scheduler.py`: triage-response action creation uses `allocate_child`
  on the relevant parent (depth-2+). The change-detection loop is unchanged in
  shape but now resolves and updates the root (via the root-only
  `get_item_by_source_id`).
- `storage/postgres/items.py`: `get_item_by_source_id` gains
  `AND parent_item_id IS NULL`.
- `providers/llm/context.py`: add `item_paths` to `LLMCallContext` /
  `llm_call_context(...)`; call sites pass the relevant item path ids; the
  recording bridge in `runtime/app.py` prefers `context.item_paths` for
  `LlmCallRecord.items` when present.

## API

Additions to `api/items.py` (`/api` prefix):
- `GET /api/items/{path}` — resolve by path id (`123` or `123.1.2`; dots are a
  valid single path segment, verified to not conflict with int
  `PATCH/DELETE/{item_id}` (different methods) nor with the static
  `/items/search` route when registered after it).
  Returns:
  ```json
  {
    "item": { "...": "..." },
    "ancestors": [{"id": 0, "path": "", "summary": "", "status": ""}],
    "children": [{"id": 0, "path": "", "seq": 0, "summary": "",
                   "status": "", "priority": "", "has_children": false}]
  }
  ```
  One level of children + `has_children` flags (lazy expand). Deeper levels fetch
  via the same endpoint per child.

## UI

- New route `/items/:path` → `pages/ItemPage.tsx` (registered as `/items/*` so a
  dotted path is captured whole via the route splat). One component serves both
  the "item page" and the "action page" — the only difference is the breadcrumb:
  - Root `#123`: breadcrumb is `#123`; body shows the source artifact + its
    extracted children listed collapsed.
  - Action `#123.1.2`: breadcrumb `#123 / #123.1 / #123.1.2` (each segment a
    link); body shows the action detail + its own children.
- Children render collapsed (path id, summary, status/priority); chevron lazy-
  loads the next level.
- Wire path links wherever an id/action appears: `ActionItems`, `Triage` /
  `TriageDetail`, `Ingestion` funnel, `Search` results, and the LLM Infra
  `items` column — all become clickable `→ /items/{path}`. Surfaces whose API
  payload already carries `path` (`ActionItems`, `Search` results, and the LLM
  Infra `items` column after D3 stamping) render live links; surfaces whose
  payload does not yet carry `path` (`Ingestion` funnel `ActivityItem`,
  `TriageDetail` `TriageCard`) render a presence-gated link that is a no-op today
  and lights up when the payload later includes `path`.
- New hook `useItem(path)` in `hooks/useItems.ts`. TS item types gain
  `seq` / `path`.

## Migration

`014_item_lineage.py` (Alembic; latest existing revision is `013_llm_calls`, so
`down_revision = "013"`; verified against `src/workbench/migrations/versions/` —
`013` is the highest, `014` is new):
- Add `seq`, `path`; add `INGESTED`/`EXTRACTED` enum values; add the constraints
  and indexes above.
- Tests provision the schema out-of-band via `alembic upgrade head`
  (`tests/conftest.py` only `TRUNCATE`s); every DB-touching task must run
  `alembic upgrade head` before asserting.
- Backfill (handles non-empty DBs; no-op if empty):
  - roots (`parent_item_id IS NULL`): `path = id::text`.
  - children: `seq = row_number() OVER (PARTITION BY parent_item_id ORDER BY id)`;
    `path = parent.path || '.' || seq`, applied iteratively by depth (recursive
    CTE) so multi-level chains resolve.
  - set `path NOT NULL` after backfill.

## Testing

- Backend unit: allocator produces `123` / `123.1` / `123.1.2`; concurrent
  sibling creation never collides (unique + retry); deletion leaves gaps without
  renumber; partial-unique blocks duplicate roots; path lookup + ancestors /
  children queries; `get_item_by_source_id` returns the root (not a child) when
  both exist for one `(source_type, source_id)`.
- Pipeline: enqueue births a root at `INGESTED` carrying the source snapshot;
  extraction creates depth-1 children with verdicts and moves the root to
  `EXTRACTED`; triage response creates depth-2 action under the right parent; LLM
  `items` carry path ids; re-poll change-detection resolves and diffs the root.
- Migration: round-trip on a seeded non-empty DB asserts correct backfilled paths
  across 3 levels.
- UI: `ItemPage` renders breadcrumb for root vs action, lazy-expands children;
  path links resolve; existing `ActionItems` / `Triage` link wiring.
- Run full suites (baseline: 643 backend / 498 UI).

## Out of scope

- Reparenting / moving subtrees (precluded by immutability).
- `ltree` / closure-table subtree analytics (revisit only if workload grows).
- Changing the `processed`-store dedup mechanism (the partial unique constraint
  is an integrity backstop alongside it, not a replacement).

## Open questions

None outstanding. Granularity (1 source → 1 root, everything derived nests),
depth (unbounded), and the action-id scheme (`#parent.seq`) are all confirmed.
Root/child share the same `(source_type, source_id)`; the root is disambiguated
as the `parent_item_id IS NULL` row, and `get_item_by_source_id` resolves it
root-only.
