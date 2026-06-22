# Item-Detail Popup (URL-addressable, app-wide) — Design

## Goal

Clicking any item anywhere in the dashboard opens a deep-linkable **Dialog**
showing that item's rich detail, instead of navigating away. This also fixes a
crash on the Search page (`#/search`): it currently feeds lean `FunnelItem` data
into a detail component that expects the rich `SearchItem` shape, hidden by an
`as unknown as SearchItem[]` cast, so it throws `Cannot read properties of
undefined (reading 'length')` at `SearchItemDetail.tsx:113` (`item.tags.length`)
the moment a result is selected.

## Root cause (the crash this design also resolves)

- The Search page uses `useSearchItems` → `GET /api/funnel/items`, which returns
  `FunnelItem` = `{id, source, summary, stages, verdict, created_at}` — no
  `tags/kind/priority/state/relevance/llm_summary/context`.
- It casts that to `SearchItem[]` (`Search.tsx:73`) and renders
  `SearchItemDetail`, which reads the missing rich fields → crash.
- Tests pass only because MSW mocks return the rich shape the real backend never
  provides.
- The rich data **does** exist via `GET /api/items/search` (returns `tags`,
  `llm_summary`, `enriched_context`, `processing_log`, `verdict`, `priority`,
  `status`, `category`, `path`, …). The bug is the wrong endpoint + blind cast.

## Decisions (locked during brainstorming)

- **Scope:** app-wide — the popup applies to the Search page AND item links on
  other surfaces (ResultRow, LiveTail, ActionItems, TriageDetail, SystemStatus).
- **Empty state:** the Search page shows a "type to search" prompt before input
  (the rich endpoint requires `q >= 2` chars).
- **URL behavior:** URL-addressable via `?item=<id>` — shareable/bookmarkable,
  Back closes the popup, deep-link on load opens it directly.
- **Identifier:** the popup keys on the integer `id` (always present where an
  item is shown). `path` (the sparse, nascent lineage identifier) is optional and
  only powers an "open full page ↗" link to `ItemPage`.
- **Popup content:** the **rich item detail** (summary, tags, llm_summary,
  contextual payload, processing log, verdict, actions) — NOT the path/lineage
  children tree, which stays on the full-page `ItemPage` (`/items/{path}`).

## Data model note (the crux)

Two identifiers coexist: integer `id` (always present) and hierarchical `path`
(sparse lineage stub, frequently null). Today's app-wide item links render only
when `path` exists (`{item.path && <Link to={/items/${path}}>}`), so most items
aren't clickable at all. Keying the popup on `id` makes every shown item
clickable regardless of `path`.

Rich detail fields come from the `items` table projection that
`GET /api/items/search` already builds:
`id, source_type, source_id, summary, category, origin, priority, status,
kind (action|item), path, created_at, updated_at, tags, llm_summary,
enriched_context, processing_log, verdict{action,priority,confidence}`.

## Architecture & data flow

```
item shown anywhere ──(ItemLink, sets ?item=<id>)──► URL ?item=<id>
                                                        │
                              useItemDialog (useSearchParams) opens Dialog
                                                        │
                              useItemDetail(id) ─► GET /api/items/by-id/{id}
                                                        │
                              toSearchItem(apiObj)  (adapter)
                                                        │
                              ItemDetailDialog renders rich detail body
                                   └─ "open full page ↗" → /items/{path} (if path)

Search page: useItemsSearch(q) ─► GET /api/items/search ─► toSearchItem[] ─► rows
             row click sets ?item=<id> (same Dialog).  q<2 ⇒ "type to search".
```

## Components

### Backend (one addition)
- `GET /api/items/by-id/{item_id}` (`api/items.py`): rich detail for one integer
  id. Factor the existing `search_items` row→dict projection into a shared
  `_row_to_search_item(row)` helper; reuse it here with `WHERE id = $1`. Return
  `404 {"detail": "Item not found"}` when absent. Distinct `by-id` segment avoids
  colliding with the existing `/items/{path}` route.

### Frontend
1. **Adapter + type** — `lib/types/search.ts` stays the UI contract; add
   `toSearchItem(api)` that maps the API object → `SearchItem`:
   `source_type→source` (and `→kind`), `status→state`, `enriched_context→context`
   (non-empty object else `null`), `processing_log→stages` mapped **per entry** to the
   `FunnelStage` shape (`{stage,label,outcome}` → `{filterId, outcome, reason, label}`; the
   detail body needs `filterId`, which `processing_log` lacks), `relevance` default `0`,
   `verdict` mapped (the API
   verdict has no `rationale`; the detail renders it as empty, never crashes),
   `tags`/`path` passed through with safe defaults (`tags: []`, `path?`). Removes
   the `as unknown as SearchItem[]` cast.
2. **Hooks** (`hooks/`) — `useItemsSearch(q)` → `GET /api/items/search` mapped to
   `SearchItem[]` (enabled only when `q.length >= 2`); `useItemDetail(id)` →
   `GET /api/items/by-id/{id}` mapped to `SearchItem`.
3. **`ItemDetailDialog`** — the existing `Dialog` (`components/ui/dialog.tsx`)
   wrapping the rich detail body (extracted from today's `SearchItemDetail`:
   header, tags, llm_summary, contextual payload via `ItemContext`, processing
   log via `FunnelStage`, verdict, actions). States: loading skeleton, 404
   ("item not found"), error (message + request id). Shows "open full page ↗" →
   `/items/{path}` only when `path` is present.
4. **URL sync** — `useItemDialog()` built on `useSearchParams`: reads `?item`,
   opens the dialog and triggers `useItemDetail`; closing removes the param;
   browser Back closes; a page loaded with `?item=<id>` opens directly.
5. **`ItemLink`** — shared clickable item reference that sets `?item=<id>` (no
   route navigation). Replaces the conditional `<Link to={/items/${path}}>` at:
   `components/search/ResultRow.tsx`, `components/LiveTail.tsx`,
   `pages/ActionItems.tsx`, `pages/TriageDetail.tsx`, `pages/SystemStatus.tsx`.
   Each site already exposes the item's `id`; verify per site and use it.
6. **Search page rewrite** (`pages/Search.tsx`) — use `useItemsSearch(debouncedQ)`;
   render rows that open the dialog on click (via `ItemLink`/`?item`); remove the
   inline master/detail panel and `selectedId` state; empty/`<2`-char state shows
   a "type to search" prompt; keep the kind filter (maps to `category`/`kind`).
7. **Retire** — the panel role of `SearchItemDetail` becomes the dialog body
   component; the `useSearchItems`→`/api/funnel/items` usage and the cast are
   removed from the search path. `ItemPage` (`/items/{path}`) is unchanged and
   remains the lineage/children view.

## Error handling

- Adapter is total: missing/null API fields map to safe defaults (`tags: []`,
  `context: null`, `relevance: 0`, `verdict` fields nullable).
- Dialog: pending → skeleton; `ApiError` 404 → "item not found"; other errors →
  message + `X-Request-ID` (reuse the existing `ApiError` pattern).
- Search page: `<2` chars → "type to search"; `isError` → existing error panel.

## Testing

- **Backend (pytest):** `GET /api/items/by-id/{id}` — found returns the rich
  projection; missing returns `404`; the shared `_row_to_search_item` mapping is
  asserted (tags/enriched_context/processing_log JSON-decoded, verdict shaped).
- **Frontend (vitest):**
  - `toSearchItem` adapter: field mapping + defaults (the type-drift guard).
  - `useItemsSearch`/`useItemDetail` via MSW returning the **real**
    `/api/items/search` and `/api/items/by-id/{id}` shapes (correcting the mocks
    that masked the original bug).
  - `ItemDetailDialog`: renders fields; loading skeleton; 404 → "item not found";
    "open full page" link present only when `path` set.
  - URL sync: `?item=<id>` opens + fetches; close clears the param; deep-link on
    mount opens directly.
  - `ItemLink`: click sets `?item=<id>` without navigating.
  - Search page: `<2` chars shows "type to search"; results list renders; row
    click opens the dialog; no crash with real-shaped data.

## Out of scope (YAGNI)

- Showing the path/lineage "What touched this" / children tree inside the popup
  (stays on `ItemPage`).
- Unifying the `id`/`path` identifier systems (the lineage path remains a stub).
- Source-map de-minification, rich-context rendering beyond what
  `enriched_context` already provides.

## Slices (for the implementation plan)

1. Backend `GET /api/items/by-id/{id}` + shared `_row_to_search_item` (+ tests).
2. Frontend adapter (`toSearchItem`) + `useItemsSearch`/`useItemDetail` (+ tests).
3. `ItemDetailDialog` + `useItemDialog` URL sync (+ tests).
4. Search page rewrite to list + dialog + "type to search" (+ tests).
5. `ItemLink` and the app-wide swap across the five surfaces (+ tests).

## Files touched

New (files added):
- `ui/src/hooks/useItemDetail.ts` (or extend an items hook)
- `ui/src/lib/search-adapter.ts` (`toSearchItem`)
- `ui/src/components/ItemDetailDialog.tsx`
- `ui/src/components/ItemDetailBody.tsx` (extracted rich detail body)
- `ui/src/components/ItemLink.tsx`
- `ui/src/hooks/useItemDialog.ts`
- tests alongside each.

Modified:
- `src/workbench/api/items.py` (add `by-id` route + shared `_row_to_search_item` mapper)
- `ui/src/pages/Search.tsx` (rewrite to list + dialog)
- `ui/src/components/search/ResultRow.tsx`, `ui/src/components/LiveTail.tsx`,
  `ui/src/pages/ActionItems.tsx`, `ui/src/pages/TriageDetail.tsx`,
  `ui/src/pages/SystemStatus.tsx` (use `ItemLink`)
- `ui/src/App.tsx` (mount the dialog at app root so `?item` works on any route)
- MSW handlers/test fixtures (real shapes)
