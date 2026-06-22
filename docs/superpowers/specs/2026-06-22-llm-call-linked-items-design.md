# Real Item IDs on LLM Calls (clickable) — Design

## Goal

In the LLM Infra view (System Status → LLM Infra), opening an LLM call shows the
**real persisted item ID(s)** that call processed, as **clickable chips** that
open the existing item-detail popup. Works for batched and non-batched calls.

## Background / why this is possible

Earlier this was thought infeasible because batched subcalls are created at
pre-persistence scoring time (no DB id; `subcall.item` is only the batch index
`str(idx)`). But the cross-entity lineage already records a usable linkage:
`pipeline/engine.py` calls
`entity_links.record_by_correlation("llm_call", correlation_id, [item.path])`
*after* the item is persisted, so `entity_item_links` maps an llm_call's
`correlation_id` → the real persisted `item_id`/`item_path`.

Live data confirms it: **403 `llm_call` links, all with a resolvable `item_id`**
(278/278 items exist); the correlation join yields, e.g., batched call `2425` →
items `{6702, 6703, 6704}`, non-batched `2432` → `{6707}`. Every linked id
resolves via `GET /api/items/by-id/{id}` (the popup built in the prior feature).

## Decisions (locked during brainstorming)

- **Granularity: call-level set.** Show the call's linked items as clickable
  chips. The correlation linkage is set-based (correlation → the call's items),
  so we do NOT claim which subcall (`#0`/`#1`) maps to which id. (Per-subcall
  mapping would need an ordered/indexed linkage recorded in the pipeline — out
  of scope.)
- **Chip content: ID + summary snippet** (e.g. `#6702 · fix the thing`).
- **Click target:** the existing `?item=<id>` item-detail popup (`ItemLink`).
- **Separate from subcall selectors:** the batch-position selector buttons stay
  plain index labels (the prior de-linkify fix); this is a distinct "Linked
  items" section showing the real items.

## Architecture & data flow

```
LLM detail dialog ──GET /api/llm/calls/{id}──► _detail_view(rec)
                                                 └─ linked_items:
                                                    entity_links.linked_items_for_correlation(rec.correlation_id)
                                                      = entity_item_links (entity_type='llm_call', correlation_id=$1)
                                                        ⨝ items  →  [{id, path, summary}]
dialog "Linked items" → ItemLink chips "#{id} · {summary}" → sets ?item=id → existing ItemDetailDialog
```

## Components

### Backend
- **`EntityLinkStore.linked_items_for_correlation(correlation_id: str | None) -> list[LinkedItem]`**
  (`storage/base.py` interface + `storage/postgres/entity_links.py` impl). One
  query joining `entity_item_links` to `items`:
  ```sql
  SELECT e.item_id AS id, e.item_path AS path, i.summary
    FROM entity_item_links e JOIN items i ON i.id = e.item_id
   WHERE e.entity_type = 'llm_call' AND e.correlation_id = $1
   ORDER BY e.item_id
  ```
  Returns `[]` when `correlation_id` is `None`. `LinkedItem` is a small typed
  shape `{id: int, path: str | None, summary: str}` (a Pydantic model or plain
  dict — implementer's choice, but typed at the interface). entity_links is
  already documented as "the only reader/writer of entity_item_links," so this
  read belongs there.
- **`api/llm.py` `_detail_view(rec)`** gains `linked_items`. Because
  `_detail_view` currently takes only `rec`, the linkage read happens in
  `get_call_detail` (which has `request`/`stores`) and is passed in — i.e.
  `_detail_view(rec, linked_items)`. `get_call_detail` calls
  `stores.entity_links.linked_items_for_correlation(rec.correlation_id)` and
  includes the serialized list. Other fields unchanged. The `404` paths
  (bad/missing call id) are unchanged.

### Frontend (`ui/src/pages/SystemStatus.tsx`)
- `LLMCallDetailData` type gains
  `linked_items: { id: number; path: string | null; summary: string }[]`.
- `useLLMCallDetail` already returns `LLMCallDetailData`; the default value used
  on pending (`{ sysPrompt: '', subcalls: [] }`) gains `linked_items: []`.
- The `LLMCallDetail` dialog renders a **"Linked items"** section (after the
  subcall selector / near the header): a wrapped row of chips, each
  `<ItemLink id={it.id}>#{it.id} · {it.summary}</ItemLink>` (truncated summary).
  `ItemLink` (from the prior feature) sets `?item=<id>`; the app-root
  `ItemDetailDialog` opens. The section is hidden when `linked_items` is empty.
- Import `ItemLink` into `SystemStatus.tsx`.

## Error handling / coverage

- Calls without a `correlation_id` (~half) or with no resolvable links → empty
  `linked_items` → the section is not rendered. Never an error.
- The query inner-joins `items`, so a link whose item was deleted is silently
  omitted.
- Reuses the verified `/api/items/by-id` popup for the actual detail; nothing new
  on the click path.

## Out of scope (YAGNI)

- Per-subcall (`#N` → exact item) attribution (needs an ordered linkage recorded
  at pipeline time).
- Backfilling correlation links for historical calls that have none.
- Changing the subcall selector buttons (they stay plain index labels).

## Testing

- **Backend (pytest):** `linked_items_for_correlation` — seed an llm_call-style
  correlation in `entity_item_links` + matching `items`, assert it returns
  `[{id, path, summary}]` joined correctly and ordered; returns `[]` for `None`
  correlation and for an unknown correlation. `get_call_detail` includes
  `linked_items` for a call with a correlation, `[]` otherwise.
- **Frontend (vitest):** the `LLMCallDetail` dialog renders a chip per
  `linked_items` entry showing `#{id} · {summary}`; clicking a chip sets
  `?item=<id>`; the section is absent when `linked_items` is `[]`. Extend the
  existing `SystemStatus.test.tsx` LLM fixtures with `linked_items`.

## Files touched

Modified:
- `src/workbench/storage/base.py` (add `linked_items_for_correlation` to `EntityLinkStore` + a `LinkedItem` type)
- `src/workbench/storage/postgres/entity_links.py` (implement it)
- `src/workbench/api/llm.py` (`_detail_view` + `get_call_detail` include `linked_items`)
- `ui/src/pages/SystemStatus.tsx` (`LLMCallDetailData` type + "Linked items" section + `ItemLink` import)
- `ui/src/pages/SystemStatus.test.tsx` (fixtures + tests)
- tests: a backend test file for the store method + endpoint

## Slices (for the plan)

1. Backend store method `linked_items_for_correlation` (+ interface + tests).
2. `api/llm.py` detail endpoint includes `linked_items` (+ test).
3. Frontend "Linked items" chips section in the LLM detail dialog (+ tests).
