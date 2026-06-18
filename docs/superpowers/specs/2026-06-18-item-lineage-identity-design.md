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
  (migration `e298e89` moved from UUID strings to integer surrogate keys).
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

### D3 — Birth at ingestion

`PipelineEngine.enqueue` (which already dedupes and creates the job/queue entry)
also creates the root `Item` row with status `INGESTED`, so the autoincrement
assigns `#123` immediately and the queue entry carries `root_item_id`. The same
id then exists for the entire journey. The real path id is stamped into
`LLMCallContext` so `LlmCallRecord.items` records `123`, `123.1` instead of
free-text summaries (closes gap #1; the LLM Infra `items` column becomes real
lineage references).

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
    closes gap #4 (never two roots for one source thing).
- Indexes: B-tree on `path` with `text_pattern_ops` (indexed `LIKE '123.%'`
  subtree scans); B-tree on `parent_item_id`.

### Allocation seam

All path/seq logic lives in one pair of store methods so the denormalized `path`
never leaks into call sites:
- `create_root(...)` — insert, `RETURNING id`, then set `path = str(id)`.
- `allocate_child(parent, ...)` — `seq = COALESCE(MAX(seq),0)+1` over siblings
  within the insert txn; `path = f"{parent.path}.{seq}"`; on
  `UNIQUE(parent_item_id, seq)` conflict, retry.

## Pipeline / scheduler changes

- `pipeline/engine.py`: create root at `enqueue` (`INGESTED`); on extraction
  create depth-1 children via `allocate_child` and apply verdicts to them
  (`EXTRACTED` for the root once children exist).
- `pipeline/scheduler.py`: triage-response action creation uses `allocate_child`
  on the relevant parent (depth-2+).
- `providers/llm/context.py` call sites: stamp the item's path id into
  `LLMCallContext` so recorded calls carry real lineage references.

## API

Additions to `api/items.py` (`/api` prefix):
- `GET /api/items/{path}` — resolve by path id (`123` or `123.1.2`; dots are a
  valid single path segment, no conflict with int `PATCH/DELETE/{item_id}`).
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

- New route `/items/:path` → `pages/ItemPage.tsx`. One component serves both the
  "item page" and the "action page" — the only difference is the breadcrumb:
  - Root `#123`: breadcrumb is `#123`; body shows the source artifact + its
    extracted children listed collapsed.
  - Action `#123.1.2`: breadcrumb `#123 / #123.1 / #123.1.2` (each segment a
    link); body shows the action detail + its own children.
- Children render collapsed (path id, summary, status/priority); chevron lazy-
  loads the next level.
- Wire path links wherever an id/action appears: `ActionItems`, `Triage` /
  `TriageDetail`, `Ingestion` funnel, `Search` results, and the LLM Infra
  `items` column — all become clickable `→ /items/{path}`.
- New hook `useItem(path)` in `hooks/useItems.ts`. TS item types gain
  `seq` / `path`.

## Migration

`012_item_lineage.py` (Alembic; latest is `011`):
- Add `seq`, `path`; add `INGESTED`/`EXTRACTED` enum values; add the constraints
  and indexes above.
- Backfill (handles non-empty DBs; no-op if empty — 010/011 were wipe-and-fresh):
  - roots (`parent_item_id IS NULL`): `path = id::text`.
  - children: `seq = row_number() OVER (PARTITION BY parent_item_id ORDER BY id)`;
    `path = parent.path || '.' || seq`, applied iteratively by depth (CTE) so
    multi-level chains resolve.
  - set `path NOT NULL` after backfill.

## Testing

- Backend unit: allocator produces `123` / `123.1` / `123.1.2`; concurrent
  sibling creation never collides (unique + retry); deletion leaves gaps without
  renumber; partial-unique blocks duplicate roots; path lookup + ancestors /
  children queries.
- Pipeline: enqueue births a root at `INGESTED`; extraction creates depth-1
  children with verdicts; triage response creates depth-2 action under the right
  parent; LLM `items` carry path ids.
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
