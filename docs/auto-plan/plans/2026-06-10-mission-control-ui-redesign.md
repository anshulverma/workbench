I now have a thorough understanding of the codebase. Let me produce the implementation plan.

# WorkBench Dashboard Design Upgrade -- Implementation Plan

## Slice Dependency Graph

```
Slice 1 (Storage)  ─────────────────────────┐
                                             ├──> Slice 4 (API endpoint)
Slice 2 (SmoothSparkline + StatusTile) ──┐   │
                                         │   │
Slice 3 (Brand assets + chrome) ─────┐   │   │
                                     │   │   │
                                     ├───┴───┴──> Slice 6 (Overview rewrite)
Slice 5 (SourceFlow + hook) ─────────┘
```

Slices 1, 2, 3 can run in parallel. Slice 4 depends on 1. Slice 5 depends on 4 (for types). Slice 6 depends on all.

---

## Slice 1: Storage Layer -- Three New Aggregate Methods

**Complexity**: S

**Description**: Add three read-only aggregate query methods to the storage interfaces and their PostgreSQL implementations. No schema changes, no migrations -- these are GROUP BY queries over existing tables and columns (`items.source_type`, `items.origin`, `ingestion_queue.status`, `ingestion_runs.source_id`, `source_configs.adapter_type`).

**Dependencies**: None (foundation slice)

**Parallelizable with**: Slices 2, 3

### Files to Modify

1. **`src/workbench/storage/base.py`** -- Add two abstract methods:
   - `ItemStore.count_by_source_and_origin() -> dict[tuple[str, str], int]` after the existing `count_by_source()` method (line ~74)
   - `IngestionQueueStore.count_dead_letters_by_source() -> dict[str, int]` after the existing `count_by_source()` method (line ~261)

2. **`src/workbench/storage/postgres/items.py`** -- Add implementation of `count_by_source_and_origin()` on `PgItemStore`:
   ```python
   async def count_by_source_and_origin(self) -> dict[tuple[str, str], int]:
       rows = await self.pool.fetch(
           "SELECT source_type, origin, COUNT(*) AS cnt FROM items GROUP BY source_type, origin"
       )
       return {(r["source_type"], r["origin"]): int(r["cnt"]) for r in rows}
   ```
   Place after the existing `count_by_source()` method (line ~161).

3. **`src/workbench/storage/postgres/ingestion_queue.py`** -- Add implementation of `count_dead_letters_by_source()` on `PgIngestionQueueStore`:
   ```python
   async def count_dead_letters_by_source(self) -> dict[str, int]:
       rows = await self.pool.fetch(
           "SELECT source_type AS k, COUNT(*) AS cnt FROM ingestion_queue "
           "WHERE status = 'dead_letter' GROUP BY source_type"
       )
       return {r["k"]: int(r["cnt"]) for r in rows}
   ```
   Place after the existing `count_by_source()` method (line ~151).

4. **`src/workbench/storage/ingestion_runs.py`** -- Add abstract method `total_enqueued_by_source() -> dict[str, int]` on `IngestionRunStore` (after `success_rate`, line ~30), and implementation on `PgIngestionRunStore`:
   ```python
   async def total_enqueued_by_source(self) -> dict[str, int]:
       rows = await self.pool.fetch(
           "SELECT s.adapter_type, COALESCE(SUM(r.raw_enqueued), 0) AS total "
           "FROM ingestion_runs r "
           "JOIN source_configs s ON r.source_id = s.id "
           "GROUP BY s.adapter_type"
       )
       return {r["adapter_type"]: int(r["total"]) for r in rows}
   ```
   Place after the existing `success_rate()` implementation (line ~117).

### Tests

**File**: `tests/test_storage.py` (existing, append new tests)

6 new test cases:
1. `test_count_by_source_and_origin_groups_correctly` -- Insert items with different (source_type, origin) combos, verify grouped counts
2. `test_count_by_source_and_origin_empty_table` -- No items returns empty dict
3. `test_count_dead_letters_by_source_returns_only_dead_letter` -- Insert queue entries with mixed statuses, verify only dead_letter counted
4. `test_count_dead_letters_by_source_no_dead_letters` -- Returns empty dict when no dead letters exist
5. `test_total_enqueued_by_source_joins_source_configs` -- Create source configs + ingestion runs, verify join produces correct adapter_type grouping
6. `test_total_enqueued_by_source_no_runs` -- Returns empty dict when no ingestion runs exist

### Files NOT Modified
- No Alembic migration needed
- No domain model changes

---

## Slice 2: SmoothSparkline + StatusTile Components

**Complexity**: M

**Description**: Create two new leaf UI components with no API dependencies. `SmoothSparkline` is a Catmull-Rom curved SVG sparkline (replaces Recharts for the Signal Velocity tile). `StatusTile` and `StatusTilePrimary` are clickable metric tiles for the status strip.

**Dependencies**: None (leaf components)

**Parallelizable with**: Slices 1, 3

### Files to Create

1. **`ui/src/components/SmoothSparkline.tsx`**
   - Props: `{ data, color?, height?, fill?, className? }`
   - `toCoordinates()` function mapping data to `[x, y]` pairs
   - `smoothPath()` Catmull-Rom to cubic Bezier conversion
   - SVG with viewBox `0 0 100 {boxH}`, `preserveAspectRatio="none"`
   - Two paths: area fill (linearGradient, stopOpacity 0.28 to 0) + stroke line (strokeWidth 1.5, non-scaling-stroke)
   - Gradient ID via `useId()` for instance uniqueness
   - Degenerate states: 0 items = centered em-dash "---"; 1 item = single 6px dot; 2+ items = smooth curve
   - All states render `aria-hidden="true"`

2. **`ui/src/components/StatusTile.tsx`** (exports both `StatusTile` and `StatusTilePrimary`)
   - `StatusTilePrimary`: `<button>` spanning 2 grid cols, `bg-primary text-primary-foreground`, shows "Initiate Triage" + ArrowRight + pending count + P0 count. Hover: brightness(.93), translateY(-1px). Focus: outline ring.
   - `StatusTile`: `<button>` with `bg-card border border-border rounded-md`. Label (mono 10px uppercase) + value (mono 20px bold). ArrowUpRight icon on hover. `danger` prop applies `text-destructive` + destructive border tint.
   - Both use Tailwind utility classes (not raw CSS `.wb-tile` classes)
   - `value` prop is `React.ReactNode` -- no internal null coercion

### Files to Create (Tests)

3. **`ui/src/components/SmoothSparkline.test.tsx`** -- 6 tests:
   - Empty data renders em-dash
   - Single point renders dot
   - Multi-point renders SVG with `<path>`
   - Fill mode sets height to 100%
   - All states render `aria-hidden="true"`
   - `toCoordinates` produces correct [x, y] pairs for known input (export the function or test through rendered output)

4. **`ui/src/components/StatusTile.test.tsx`** -- 6 tests:
   - Renders label and value
   - onClick fires navigation callback
   - danger variant applies destructive styling class
   - Arrow icon appears on hover (or is present in DOM with show-on-hover class)
   - StatusTilePrimary renders pending count and P0 count
   - StatusTile renders when value is a string like 'n/a'

---

## Slice 3: Brand SVG Assets + Chrome Updates

**Complexity**: S

**Description**: Copy the two brand SVG files from the design prototype to `ui/public/`, update the AppSidebar with a WB icon button, and update the TopBar wordmark.

**Dependencies**: None

**Parallelizable with**: Slices 1, 2

### Files to Create

1. **`ui/public/wb-icon.svg`** -- Copy from `/tmp/design_bundle/workbench/project/app/assets/wb-icon.svg`. 160x160 viewBox, dark square with W letterform, amber "B" badge (#D97706), amber underline.

2. **`ui/public/wb-primary-lockup.svg`** -- Copy from `/tmp/design_bundle/workbench/project/app/assets/wb-primary-lockup.svg`. 701x160 viewBox, icon + "WorkBench" text.

### Files to Modify

3. **`ui/src/components/AppSidebar.tsx`**
   - Add `useNavigate` import from react-router-dom
   - Insert a `<button>` before the `<TooltipProvider>` block (before line 59):
     - `mb-3`, 36x36 image of `/wb-icon.svg`, `onClick={() => navigate('/')}`, `aria-label="WorkBench home"`
   - The button is visually above the nav list, inside the `<nav>` element

4. **`ui/src/components/TopBar.tsx`**
   - Add `useNavigate` import
   - Replace the brand mark div (lines 121-131) with a `<button>` containing:
     - `<img src="/wb-icon.svg" width={28} height={28} />`
     - Split wordmark span: "Work" (bold 700) + "B" (bold 700, text-primary) + "ench" (medium 500)
     - Font: `font-display text-[15px] tracking-tight`
     - `onClick={() => navigate('/')}`, `aria-label="WorkBench home"`

### Tests

- Update existing `AppShell.test.tsx` if it asserts on sidebar content (verify WB icon image renders)
- Update existing TopBar assertions if any test checks for the old "W" brand mark text

---

## Slice 4: Flow Matrix API Endpoint

**Complexity**: M

**Description**: Add `GET /api/stats/flow-matrix` endpoint to `stats.py`. Composes three storage queries into the `FlowMatrix` response shape. Includes `_compute_ingestion_rate` and `_compute_egress_rate` helper functions.

**Dependencies**: Slice 1 (storage methods must exist)

**Parallelizable with**: Slices 2, 3 (but not 1)

### Files to Modify

1. **`src/workbench/api/stats.py`** -- Add at the end of the file:
   - `_compute_ingestion_rate(stores) -> float | None` -- SUM(raw_enqueued) / hours_elapsed from earliest to latest successful ingestion run. Returns None when < 2 runs or zero enqueued.
   - `_compute_egress_rate(stores) -> float | None` -- COUNT items with completed_at in last 24h / 24. Returns None when zero completed.
   - `@router.get("/flow-matrix") async def flow_matrix(request: Request)`:
     - Calls `stores.items.count_by_source_and_origin()`, `stores.ingestion_queue.count_dead_letters_by_source()`, `stores.ingestion_runs.total_enqueued_by_source()`
     - Enumerates source types (sorted, excluding manual-origin-only sources)
     - Builds matrix: per source row = `[action_items, triage_queue, filtered_out, errors]`
     - `filtered_out = max(0, vol - action - triage - errors)`
     - Manual-origin items excluded from all counts
     - Fixed output order: action_items, triage_queue, filtered_out, errors
     - Returns `{ sources, outputs, matrix, rates: { ingestion_per_hour, egress_per_hour }, window_hours: null }`

### Tests

**File**: `tests/test_stats_api.py` (existing, append new tests)

7 new test cases:
1. `test_flow_matrix_returns_200_with_correct_shape` -- Verify response keys and types
2. `test_flow_matrix_sources_match_configured` -- Insert source configs + items, verify sources list
3. `test_flow_matrix_rows_sum_to_source_volumes` -- Verify matrix[i] sums to sources[i].vol
4. `test_flow_matrix_output_order_fixed` -- Verify outputs are [action_items, triage_queue, filtered_out, errors]
5. `test_flow_matrix_rates_null_when_no_runs` -- No ingestion runs = null rates
6. `test_flow_matrix_empty_state` -- No items/sources = empty sources array, zero-vol outputs
7. `test_flow_matrix_excludes_manual_origin` -- Insert manual-origin items, verify they do not appear in matrix

---

## Slice 5: SourceFlow Component + useFlowMatrix Hook

**Complexity**: L

**Description**: Create the animated SVG Sankey diagram component and the TanStack Query hook that fetches from `/api/stats/flow-matrix`. This is the largest component -- 760x300 SVG with source/output nodes, cubic Bezier ribbons, 80-dot animation pool, hover cross-proportioning, and five UI state taxonomy handling.

**Dependencies**: Slice 4 (for the FlowMatrix type definition and API endpoint)

**Parallelizable with**: Slices 2, 3

### Files to Modify

1. **`ui/src/hooks/useStats.ts`** -- Add at the end:
   - `FlowMatrixSource`, `FlowMatrixOutput`, `FlowMatrix` type exports
   - `useFlowMatrix()` hook: `queryKey: ['stats', 'flow-matrix']`, `queryFn: () => apiGet<FlowMatrix>('/api/stats/flow-matrix')`, `refetchInterval: pollWhenVisible(30_000)`

### Files to Create

2. **`ui/src/components/SourceFlow.tsx`**
   - Props: `{ data: FlowMatrix | undefined, isLoading: boolean, isError: boolean, error?: Error | null, onNavigate?: (path: string) => void }`
   - Constants: W=760, H=300, TOP=26, BOT=26, NODE_W=12, GAP=16, xL=150, barX=350, barW=64, xR=600, barRX=414, barH=248
   - `SOURCE_STYLES` map for known source types (colors + lucide icons) + `FALLBACK_COLORS` array
   - Four fixed outputs with colors: action_items=#b79cf7, triage_queue=#9a7af0, filtered_out=#71717a, errors=#e5484d
   - SVG structure:
     - Source nodes (left): `<rect>` with proportional height, `foreignObject` label with icon + per-day rate
     - Central WorkBench bar: `<rect>` at barX with rx=10, ingestion/egress rates, WB icon
     - Output nodes (right): `<rect>` with proportional height, `foreignObject` label with icon + label text
     - Ribbons: cubic Bezier `<path>` connecting nodes to central bar, fill-opacity 0.26, hover 0.42
   - 80-dot animation pool via `requestAnimationFrame` + `useEffect` cleanup
   - Hover cross-proportioning: hovering source re-proportions outputs (and vice versa), transitions 0.28s ease
   - Motion sensitivity: all animation gated behind `prefers-reduced-motion: no-preference`; `matchMedia` check
   - Five UI states: loading (skeleton SVG), error (destructive card with retry button), empty (zero-width ribbons), normal (full animation)
   - `role="img"` + `aria-label` on SVG, `<title>` elements on node groups
   - Responsive: `min-width: 400px` with `overflow-x: auto` on container
   - Output click calls `onNavigate(path)` for navigable outputs

3. **`ui/src/components/SourceFlow.test.tsx`** -- 7 tests:
   - Loading state renders skeleton
   - Error state renders error card with retry button
   - Empty data renders zero-width ribbons (source/output labels show 0/d)
   - Normal data renders correct number of source/output nodes
   - `aria-label` present on SVG
   - Output click fires onNavigate with correct path
   - `prefers-reduced-motion: reduce` hides dots (mock `matchMedia`)

### Files to Create (Hook Tests)

4. **`ui/src/hooks/useStats.test.ts`** -- 3 tests (new file):
   - `useFlowMatrix` returns typed FlowMatrix data
   - Poll interval is 30s
   - Query key is `['stats', 'flow-matrix']`

---

## Slice 6: Overview Page Rewrite

**Complexity**: L

**Description**: Replace the entire Overview page layout. Remove Recharts charts, DataTable, TopologyPanel, and the old StatCard grid. Wire in StatusTile strip, SourceFlow Sankey hero, and Signal Velocity card with SmoothSparkline. Update the five UI state taxonomy gates for the new skeleton structure.

**Dependencies**: Slices 1, 2, 3, 4, 5 (all prior slices)

**Parallelizable with**: None (final integration slice)

### Files to Modify

1. **`ui/src/pages/Overview.tsx`** -- Full rewrite:
   - **Remove imports**: `Recharts` (Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis), `StatCard`, `ChartCard`, `Sparkline`, `Topology`, `DataTable`, `CHART_COLORS/CHART_DEFAULTS/CHART_PALETTE/TOOLTIP_CONTENT_STYLE`, `useIngestionTimeseries`, `useJobs`, `useTopology`, `Job` type, `PRIORITY_ORDER`, `CATEGORY_ORDER`, `PRIORITY_VARIANT` (keep only what HotFeed uses -- `PRIORITY_VARIANT` stays), `jobColumns`
   - **Add imports**: `StatusTile`, `StatusTilePrimary` from `@/components/StatusTile`, `SourceFlow` from `@/components/SourceFlow`, `SmoothSparkline` from `@/components/SmoothSparkline`, `useFlowMatrix` from `@/hooks/useStats`
   - **Remove components**: `TopologyPanel` function (lines 130-154), `SignalVelocityTile` function (lines 156-173) -- signal velocity is now inline in the new layout
   - **Keep**: `HotFeed` function (lines 87-128), `pct()` helper, `isUnauthorized()`, `requestIdOf()`
   - **Update `HotFeed`**: Change `CardHeader` to use divided variant styling (add border-b class)
   - **Update `Overview` function**:
     - Remove `timeseries` and `jobs` hooks; add `flowMatrix = useFlowMatrix()` and `velocitySeries = useMetricsTimeseries('signal_velocity', 24, 'hour')`
     - Update unauthorized check: remove `timeseries` and `jobs` from the array
     - **Loading state**: New skeleton grid: 7-col strip (h-20), one large skeleton (h-72), two-col row (h-48 each). Update `data-testid="overview-loading"`.
     - **Status strip**: `grid-template-columns: repeat(N, minmax(0, 1fr))` where N=8 when dead_letters > 0, else 7. Gap 10px. Contains:
       - StatusTilePrimary (span 2) navigating to `/triage`
       - StatusTile "Ingestion Queue" showing `in_flight`, navigating to `/ingestion`
       - StatusTile "Ingest Rate" showing `pct(ingestionRate)`, navigating to `/ingestion`
       - (Conditional) StatusTile danger "Dead Letters" showing `dead_letters`, navigating to `/ingestion`
       - StatusTile "Active Items" showing `active_items`, navigating to `/actions`
       - StatusTile "Sources" showing `{enabled}/{total}` + green health dot, navigating to `/sources`
       - StatusTile "Messenger" showing HealthBadge, navigating to `/messenger`
     - **Signal Flow card**: `<Card>` with divided CardHeader "Signal Flow" + subtitle, CardContent wrapping `<SourceFlow data={flowMatrix.data} isLoading={flowMatrix.isPending} isError={flowMatrix.isError} error={flowMatrix.error} onNavigate={navigate} />`
     - **Degraded banner** (conditional): amber-tinted border, TriangleAlert icon, messenger not configured message. Positioned between Signal Flow and Hot Feed row.
     - **Dead letter alert banner**: Preserved from current (lines 331-346), but now positioned after the degraded banner.
     - **Hot Feed + Signal Velocity row**: `grid-cols-[1.6fr_1fr] gap-4`. Left: `<HotFeed />`. Right: Signal Velocity card with divided CardHeader, large mono number, `<SmoothSparkline data={velocitySeries.data ?? []} fill />` with min-height 72px.
     - **Remove**: 6-column stat grid, 4 Recharts charts, Recent Jobs DataTable section

2. **`ui/src/pages/Overview.test.tsx`** -- Major update:
   - **Update mock data**: Add `FLOW_MATRIX` mock object with sources, outputs, matrix, rates
   - **Update MSW handlers**: Add `/api/stats/flow-matrix` handler, remove handlers that are no longer needed for Overview (but keep them since they may be hit by other hooks)
   - **Remove/update test cases**:
     - Remove: "renders all six stat cards" (replace with status strip test)
     - Remove: "renders the four chart cards by title"
     - Remove: "renders the recent jobs table"
     - Remove: "renders the topology panel" test
     - Remove: "renders the attention header" (replaced by StatusTilePrimary)
     - Remove: "renders the ingestion-success-rate tile" (replaced by StatusTile)
     - Remove: "keeps all existing widgets present alongside the hero region"
   - **Add/update test cases**:
     - Loading skeleton has new structure (status strip skeleton + Sankey skeleton)
     - Empty state unchanged
     - Unauthorized state unchanged
     - Error state unchanged
     - Normal state renders StatusTilePrimary with triage count
     - Normal state renders SourceFlow card (check for "Signal Flow" header)
     - Dead letter tile conditionally appears in status strip when dead_letters > 0
     - No Recharts charts or Recent Jobs table rendered
     - No TopologyPanel rendered
     - Hot Feed still renders
     - Signal Velocity card renders with SmoothSparkline

---

## Summary Table

| Slice | Title | Complexity | Dependencies | Parallelizable With | Files Created | Files Modified |
|-------|-------|-----------|-------------|---------------------|---------------|----------------|
| 1 | Storage: Three aggregate methods | S | None | 2, 3 | 0 | 4 (`base.py`, `items.py`, `ingestion_queue.py`, `ingestion_runs.py`) + tests in `test_storage.py` |
| 2 | SmoothSparkline + StatusTile | M | None | 1, 3 | 4 (`SmoothSparkline.tsx`, `StatusTile.tsx`, + 2 test files) | 0 |
| 3 | Brand SVGs + chrome updates | S | None | 1, 2 | 2 (`wb-icon.svg`, `wb-primary-lockup.svg`) | 2 (`AppSidebar.tsx`, `TopBar.tsx`) |
| 4 | Flow matrix API endpoint | M | Slice 1 | 2, 3 | 0 | 1 (`stats.py`) + tests in `test_stats_api.py` |
| 5 | SourceFlow component + hook | L | Slice 4 | 2, 3 | 2 (`SourceFlow.tsx`, `SourceFlow.test.tsx`) + 1 (`useStats.test.ts`) | 1 (`useStats.ts`) |
| 6 | Overview page rewrite | L | 1, 2, 3, 4, 5 | None | 0 | 2 (`Overview.tsx`, `Overview.test.tsx`) |

**Total files created**: 8 components/tests + 2 SVG assets = 10
**Total files modified**: 10 (4 backend + 4 frontend + 2 test files)
**Total files deleted**: 0