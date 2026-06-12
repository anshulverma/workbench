Now I have all the information needed. Let me produce the complete fixed spec.

# WorkBench Dashboard Design Upgrade -- Design Specification

## 1. Overview

This spec details the migration of a Claude Design prototype (located at `/tmp/design_bundle/workbench/project/`) into the production WorkBench React/TypeScript/Vite/shadcn/Tailwind codebase (`/home/anshulverma/workspace/workbench/ui/`). The upgrade replaces the Overview page layout, introduces three new components (SourceFlow, SmoothSparkline, StatusTile), and updates brand chrome in the sidebar rail and top bar. It also adds one new server-side API endpoint (`GET /api/stats/flow-matrix`) and three new storage-layer methods.

### Domain Glossary Reference

These terms (from CONTEXT.md and the existing domain layer at `src/workbench/domain/`) are used throughout:

- **Item** -- An extracted content entity stored in the `items` table with `source_type`, `origin` (auto_included | triaged | manual), `status`, `priority`, and `category`.
- **Triage Card** -- A TriageCard record generated for items routed to the triage queue, presented to the user via messenger or web UI.
- **Source** -- A `SourceConfig` representing a configured adapter (e.g., phabricator.diff, google_chat). Identified by `adapter_type`.
- **Ingestion Queue** -- The `IngestionQueueEntry` durable queue. Items enter as `queued`, are processed to `completed`, or exhaust retries to `dead_letter`.
- **Pipeline Job** -- A `PipelineJob` record tracking a processing run, with `items_extracted`, `items_dropped`, and status.
- **Dead Letter** -- An `IngestionQueueEntry` with `status='dead_letter'` that exhausted all retry attempts.
- **Signal Velocity** -- Items created in the last 24 hours (existing metric from `OverviewMetrics.signal_velocity`).
- **Origin** -- The pipeline routing outcome stored on an Item: `auto_included` (auto-kept), `triaged` (sent to triage queue), or `manual` (user-submitted).

### Settled Decisions (immutable)

These ADRs are frozen and must not be re-decided:

| ADR | Constraint |
|------|-----------|
| 0033 | Raw hex tokens, two-orange system (#ff6a2b primary, #ffb59a brand) |
| 0034 | Brand orange identical across light/dark themes |
| 0035 | Self-hosted variable fonts (Space Grotesk, Hanken Grotesk, JetBrains Mono), no CDN |
| 0036 | 64px icon rail, CSS grid shell, Radix tooltips |
| 0038 | Centralized chart theme module (`chart-theme.ts`) |
| 0040 | Never fabricate metrics; null for zero-denominator or degraded |
| 0041 | Topology component preserved (just removed from Overview hero) |
| 0046 | Contrast contract: #ff6a2b only on surfaces <= #2a2a2d; #0e0e11 on orange fills |

### Resolved Design Decisions

These were grilled and finalized during the design review:

1. **Tweaks panel**: Excluded from production. The accent (#ff6a2b), radius ladder (6px/4px/2px/10px), and density (Comfortable) are frozen design tokens, not user-mutable.
2. **Accent color**: Stays #ff6a2b. The prototype's #f5a623 was an exploration artifact.
3. **Corner radius**: Stays Tight (6px cards, 4px controls, 2px chips, 10px large). Not adopting Round (12px).
4. **Density**: Current Comfortable (24px main padding) is already correct. No density toggle.
5. **Flow matrix data**: New server-side endpoint required; not derivable from existing endpoints.

### Deviations from Grilled Decisions

| Grilled Decision | Original Resolution | Deviation in This Spec | Rationale |
|------------------|---------------------|------------------------|-----------|
| **Decision 8** (SourceFlow data hook ownership) | SourceFlow calls `useFlowMatrix()` internally (like Topology.tsx) | Overview calls the hook at page level and passes data as props to SourceFlow | The production codebase's Overview.tsx manages all query hooks at the page level and passes typed data down to children. HotFeed is the sole exception because it is a standalone card. SourceFlow is the hero visualization tightly integrated with Overview's five-state taxonomy gates, so page-level ownership is more consistent. The hook remains co-located in `useStats.ts` as originally resolved. See Section 3.1 for the full component API. |

---

## 2. Scope

### In Scope

| Layer | Change |
|-------|--------|
| **Server** | New `GET /api/stats/flow-matrix` endpoint in `src/workbench/api/stats.py` |
| **Storage** | Three new abstract methods on store interfaces + PostgreSQL implementations |
| **Frontend -- Components** | `SourceFlow`, `SmoothSparkline`, `StatusTile`, `StatusTilePrimary`, brand SVG assets |
| **Frontend -- Pages** | `Overview.tsx` rewrite |
| **Frontend -- Hooks** | `useFlowMatrix()` in `useStats.ts` |
| **Frontend -- Chrome** | TopBar wordmark update, AppSidebar WB icon |
| **Frontend -- Types** | `FlowMatrix` interface in `useStats.ts` |

### Out of Scope

- Tweaks panel (design-time tool only)
- Charts page -- The four Recharts charts (Ingestion area, Priority bar, Source donut, Category h-bar) and the Recent Jobs DataTable are removed from Overview in this spec. Their underlying components (`ChartCard`, `DataTable`, Recharts wrappers) remain in the codebase but are **not rendered on any page** after this change. A future spec will introduce a dedicated stats/analytics page that re-introduces these visualizations. Until that spec is delivered, these chart views are unavailable to the user. This is an intentional tradeoff: the Overview page is being redesigned around the Sankey flow visualization, and keeping the old charts alongside it would create a cluttered layout inconsistent with the design.
- Density toggle
- Accent color switching
- Radius presets
- Topology component changes (it is preserved elsewhere; just removed from Overview hero)
- Any changes to pages other than Overview
- Any changes to the domain model or pipeline logic

---

## 3. Components

### 3.1 SourceFlow

**File**: `ui/src/components/SourceFlow.tsx`

**Purpose**: Animated SVG Sankey diagram showing the flow of Items from Source adapters through WorkBench to four output buckets. The hero visualization for the Overview page.

#### Props

```typescript
interface SourceFlowProps {
  data: FlowMatrix | undefined
  isLoading: boolean
  isError: boolean
  error?: Error | null
  onNavigate?: (path: string) => void
}
```

The component does NOT call `useFlowMatrix()` internally (unlike the prototype's self-contained pattern). Instead, the Overview page calls the hook and passes data as props. This aligns with the existing pattern where Overview owns all query hooks and child components receive typed data. The loading/error/empty states are handled inside the component based on the `isLoading` and `isError` props.

**Deviation from grilled decision 8**: The grilling concluded that SourceFlow should call the hook internally (like Topology.tsx). This spec deviates from that resolution. See the Deviations table in Section 1 for the full rationale.

#### Visual Specification

All dimensions and coordinates from the design prototype (`charts.jsx` SourceFlow function):

| Constant | Value | Purpose |
|----------|-------|---------|
| `W` | 760 | SVG viewBox width |
| `H` | 300 | SVG viewBox height |
| `TOP` | 26 | Top padding |
| `BOT` | 26 | Bottom padding |
| `NODE_W` | 12 | Source/output node bar width |
| `GAP` | 16 | Vertical gap between nodes |
| `xL` | 150 | X position of left (source) nodes |
| `barX` | 350 | X position of central WorkBench bar |
| `barW` | 64 | Width of central WorkBench bar |
| `xR` | 600 | X position of right (output) nodes |
| `barRX` | 414 (barX + barW) | Right edge of central bar |
| `barH` | 248 (H - TOP - BOT) | Height of bar area |

**Source nodes** (left side): Dynamic list from `data.sources`. Each rendered as a `<rect>` with the source's color, width `NODE_W`, height proportional to volume. A `foreignObject` label to the left shows: lucide icon (17px) + mono text `{perDay}/d` where `perDay = Math.max(1, Math.round(vol / 14))`.

**Output nodes** (right side): Fixed four outputs in order:

| Index | ID | Label | Color | Icon (lucide) | Navigation target |
|-------|-----|-------|-------|---------------|-------------------|
| 0 | `action_items` | Action Items | `#b79cf7` | CircleCheckBig | `/actions` |
| 1 | `triage_queue` | Triage Queue | `#9a7af0` | ListChecks | `/triage` |
| 2 | `filtered_out` | Filtered Out | `#71717a` | Filter | (none) |
| 3 | `errors` | Errors | `#e5484d` | TriangleAlert | `/ingestion` |

**Output node color contrast certification (ADR 0046)**: The SourceFlow SVG background inherits from `var(--card)`, which resolves to `#0e0e11` in dark mode. All four output node colors have been verified against this surface:
- `#b79cf7` (Action Items): 6.2:1 contrast ratio against `#0e0e11` -- passes AA and AAA
- `#9a7af0` (Triage Queue): 4.6:1 contrast ratio against `#0e0e11` -- passes AA
- `#71717a` (Filtered Out): 4.5:1 contrast ratio against `#0e0e11` -- passes AA
- `#e5484d` (Errors): 4.6:1 contrast ratio against `#0e0e11` -- passes AA

These colors are intentionally distinct from the `CHART_PALETTE` in `chart-theme.ts` because they serve a different purpose: the Sankey outputs are semantic categories (action, triage, filter, error) with fixed meanings, not arbitrary chart series. They do not rotate or cycle. The purple tones (`#b79cf7`, `#9a7af0`) visually encode "processed output" and are consistent with common data-flow visualization conventions. These colors are defined as constants in `SourceFlow.tsx` and are not added to `chart-theme.ts`.

**Central WorkBench bar**: `<rect>` at `(barX, TOP)` with `rx="10"`, filled `var(--card)`, stroked `var(--border)` and a secondary stroke at `var(--primary)` with `strokeOpacity="0.25"`. Contains a `foreignObject` with three vertical sections:
- Top: ingestion rate (`ArrowDownToLine` icon 15px, mono bold rate number, "IN/h" micro-label in brand color)
- Center: WB icon SVG (34x34px)
- Bottom: egress rate ("OUT/h" micro-label, mono bold rate number, `ArrowUpFromLine` icon 15px in `#9a7af0`)

**Ribbons**: Cubic Bezier bands connecting source nodes to the central bar (left ribbons) and central bar to output nodes (right ribbons). Fill color matches the source/output node color. Default fill-opacity: `0.26`. On hover (isolated): `0.42`.

**Flowing dots**: 80-dot object pool animated via `requestAnimationFrame`. Each dot is a `<circle r="2.4">`. Dots spawn per-ribbon weighted by flow volume (spawn rate constant `RATE = 0.022`). Speed per dot: `0.34 + Math.random() * 0.28`. Dots follow the ribbon midline path using `getPointAtLength()`. Opacity: `0.95` when active, `0` when inactive.

**Hover interaction (cross-proportioning)**:
- Hovering a source node: the right (output) side re-proportions to show only that source's contribution to each output (from the matrix row). Left ribbons for non-hovered sources collapse to zero width.
- Hovering an output node: the left (source) side re-proportions to show only that output's intake from each source (from the matrix column). Right ribbons for non-hovered outputs collapse to zero width. Clicking a navigable output fires `onNavigate(path)`.
- Transitions: `d .28s ease` on ribbon paths, `y/height .28s ease` on node rects, `opacity .15s ease` on dimmed labels.

**Accessibility**: `role="img"` with `aria-label="Signal flow: input sources through WorkBench to outputs. Hover a source or output to see its breakdown."` Each source/output node group has a `<title>` element with the label.

**HashRouter compatibility**: The `onNavigate` callback receives paths like `'/triage'`, `'/actions'`, `'/ingestion'`. These are passed to React Router's `navigate()` function (via the Overview page), which works correctly with the HashRouter (ADR 0018) because `navigate()` operates relative to the router's base, not the browser URL directly.

**Responsive behavior**: The SVG uses `viewBox="0 0 760 300"` with the default `preserveAspectRatio="xMidYMid meet"`, so it scales down proportionally on narrow viewports. The `foreignObject` labels use pixel-based font sizes (10-13px) that remain legible down to approximately 400px container width (where the SVG renders at roughly 53% scale). Below 400px, a `min-width: 400px` CSS constraint on the SVG container with `overflow-x: auto` prevents labels from becoming unreadable. A fully simplified mobile layout is out of scope for this spec.

#### Five UI State Taxonomy

| State | Trigger | Rendering |
|-------|---------|-----------|
| **Loading** | `isLoading === true` | Skeleton SVG: same 760x300 viewBox, central bar outline rendered as a Skeleton rectangle, muted placeholder rectangles at `xL` and `xR` positions. Uses the existing `Skeleton` component's shimmer animation. |
| **Error** | `isError === true` | Error card with `border-destructive/50` border, `bg-destructive/10` background. Layout: `TriangleAlert` icon (lucide, 16px, `text-destructive`) + error message text (`error?.message ?? 'Failed to load flow data'`) + request ID if available (`error instanceof ApiError ? error.requestId : null`, rendered as `text-xs text-muted-foreground`). Below the message: a retry `<button>` styled `text-sm underline text-destructive` that calls `queryClient.invalidateQueries({ queryKey: ['stats', 'flow-matrix'] })`. This matches the page-level error card pattern used in Overview.tsx (see the `overview.isError` gate), not ChartCard which has no error state. |
| **Empty** | `data.sources.length === 0` OR all matrix values are zero | Full SVG structure renders with zero-width ribbons. Source/output labels show `0/d`. Central bar shows `0` for both rates. Honest zero state, not an error. |
| **Unauthorized** | Handled at page level by Overview's existing 401 gate | N/A (never reaches SourceFlow) |
| **Degraded** | N/A (no degraded mode specific to this widget) | N/A |

#### Motion Sensitivity

All dot animation and ribbon transitions must be gated behind `prefers-reduced-motion: no-preference`. When `prefers-reduced-motion: reduce`, dots are hidden and ribbons render at static positions without transitions.

---

### 3.2 SmoothSparkline

**File**: `ui/src/components/SmoothSparkline.tsx`

**Purpose**: Catmull-Rom curved area sparkline replacing the existing straight-segment Recharts-based `Sparkline` for use within the Signal Velocity tile. The existing `Sparkline` component is NOT deleted (other pages may use it); `SmoothSparkline` is a new component.

#### Props

```typescript
interface SmoothSparklineProps {
  data: Array<number | { count: number }>
  color?: string          // default: 'var(--primary)'
  height?: number         // default: 32; ignored when fill=true
  fill?: boolean          // default: false; when true, stretches to container
  className?: string
}
```

#### Data-to-Coordinates Mapping

The raw `data` array (numbers or `{ count: number }` objects) is transformed into `[x, y]` coordinate pairs for the `smoothPath` function as follows:

```typescript
function toCoordinates(
  data: Array<number | { count: number }>,
  boxW: number,
  boxH: number,
  padding: number = 2
): [number, number][] {
  // 1. Normalize to plain numbers
  const values = data.map((d) => (typeof d === 'number' ? d : d.count))

  // 2. Compute scale
  const max = Math.max(...values, 1) // floor at 1 to avoid division by zero
  const usableH = boxH - padding * 2

  // 3. Map to [x, y] pairs
  //    x: evenly spaced across the viewBox width
  //    y: scaled and inverted (SVG y=0 is top), clamped to [padding, boxH - padding]
  return values.map((v, i) => [
    data.length === 1 ? boxW / 2 : (i / (data.length - 1)) * boxW,
    Math.max(padding, Math.min(boxH - padding, boxH - padding - (v / max) * usableH)),
  ])
}
```

The resulting coordinate array is passed to `smoothPath()` below. When `data.length < 2`, the degenerate states apply (see table below) and `smoothPath` is not called.

#### Algorithm

Catmull-Rom to cubic Bezier conversion (from prototype `charts.jsx` `smoothPath`):

```typescript
function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return ''
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`
  }
  return d
}
```

**SVG structure**: viewBox `0 0 100 {boxH}` where `boxH = fill ? 100 : height`. `preserveAspectRatio="none"`. Two paths: area fill (with `linearGradient` from `stopOpacity="0.28"` to `stopOpacity="0"`) and stroke line (`strokeWidth="1.5"`, `vectorEffect="non-scaling-stroke"`, `strokeLinecap="round"`, `strokeLinejoin="round"`).

**Gradient ID**: Must be unique per instance. Use `useId()` (React 18+) or `useMemo(() => crypto.randomUUID().slice(0,8), [])`.

#### Degenerate States

| Data length | Rendering |
|-------------|-----------|
| 0 | Centered em-dash "---" in mono, muted foreground |
| 1 | Single 6px dot circle in `color` |
| 2+ | Smooth curve |

All states render `aria-hidden="true"` (decorative).

---

### 3.3 StatusTile / StatusTilePrimary

**File**: `ui/src/components/StatusTile.tsx`

**Purpose**: Clickable metric tiles that form the compact status strip on the Overview page. Replace the existing non-clickable `StatCard` grid and the "Attention Required" header.

#### StatusTilePrimary (the triage CTA tile)

```typescript
interface StatusTilePrimaryProps {
  pendingTriage: number
  p0Active: number
  onClick: () => void
}
```

Renders as a `<button>` spanning 2 grid columns. Styled with `bg-primary text-primary-foreground` (the orange CTA). Layout:
- Top line: "Initiate Triage" + `ArrowRight` icon (13px), mono 11px, uppercase, tracking `.06em`, weight 600, opacity 0.85
- Bottom line: Large mono number (24px, bold 700) for `pendingTriage`, then "pending . {p0Active} P0 active" (13px, weight 500)

Hover: `filter: brightness(.93)`, `translateY(-1px)`. Focus: `outline: 2px solid var(--ring)`.

#### StatusTile (individual metric tiles)

```typescript
interface StatusTileProps {
  label: string
  value: React.ReactNode
  onClick: () => void
  danger?: boolean
}
```

The `value` prop is typed as `React.ReactNode`, which means it accepts strings, numbers, JSX elements, `null`, and `undefined`. The caller is responsible for null/undefined handling before passing the value. For example, the Overview page's "Ingest Rate" tile uses `pct(ingestion_success_rate)` which already maps `null` to the string `'n/a'` (see the existing `pct()` helper in Overview.tsx). StatusTile renders the `value` prop as-is; it does not perform any null coercion internally.

Renders as a `<button>`. Styled with `bg-card border border-border rounded-md`. Layout:
- Top: Label as mono 10px uppercase section header + `ArrowUpRight` icon (12px) on the right, hidden by default, shown on hover with `opacity .65` and `translateX(2px)` transition
- Bottom: Value in mono 20px bold; `text-destructive` when `danger=true`

**HashRouter compatibility**: The `onClick` handler receives a callback from the Overview page that calls `navigate('/path')` via React Router's `useNavigate()`. These paths (e.g., `'/triage'`, `'/actions'`, `'/sources'`) work correctly with HashRouter (ADR 0018) because `navigate()` is router-relative.

CSS classes from prototype (`app.css`):
- `.wb-tile`: card background, border, rounded corners, pointer cursor, hover elevates -1px, border glows `color-mix(in srgb, var(--primary) 40%, var(--border))`
- `.wb-tile--danger`: destructive border tint, destructive background tint
- `.wb-tile-primary`: primary background, no border, brightness filter on hover

These styles should be implemented as Tailwind utility classes, not raw CSS, consistent with the production codebase.

---

### 3.4 Brand SVG Assets

**Files**:
- `ui/public/wb-icon.svg` -- The WB icon (160x160 viewBox, dark square with W letterform, amber "B" badge, amber underline)
- `ui/public/wb-primary-lockup.svg` -- Full wordmark lockup (701x160 viewBox, icon + "WorkBench" text)

Source: `/tmp/design_bundle/workbench/project/app/assets/wb-icon.svg` and `wb-primary-lockup.svg`.

The icon SVG uses `fill="#D97706"` for the amber accent elements and `fill="#F9F7F2"` for the letterforms on dark `fill="#1A1A1A"` background.

---

## 4. Pages

### 4.1 Overview Page Redesign

**File**: `ui/src/pages/Overview.tsx`

#### Current Structure (to be replaced)

```
h1 "Overview"
 Attention Required header (P0 count + "Initiate Triage" CTA)
 3-column hero: HotFeed | TopologyPanel | (IngestionSuccessRate + SignalVelocity)
 Dead letter alert banner
 6-column stat grid (6 StatCards)
 4 Recharts charts (2x2 grid)
 Recent Jobs DataTable
```

#### New Structure

```
h1 "Overview"
 Status strip (7-8 column grid of StatusTile/StatusTilePrimary)
 Signal Flow card (SourceFlow Sankey hero)
 [Conditional] Degraded messenger banner
 [Conditional] Dead letter alert banner (preserved from current)
 2-column layout: HotFeed | SignalVelocity card (with SmoothSparkline)
```

#### Status Strip Layout

Grid: `gridTemplateColumns: repeat(${deadLetters > 0 ? 8 : 7}, minmax(0, 1fr))` with `gap: 10px`.

| Position | Type | Label | Value | Navigation |
|----------|------|-------|-------|-----------|
| Span 2 cols | StatusTilePrimary | Initiate Triage | `{pending_triage}` pending + `{P0}` P0 active | `/triage` |
| 1 col | StatusTile | Ingestion Queue | `{in_flight}` | `/ingestion` |
| 1 col | StatusTile | Ingest Rate | `{pct(ingestion_success_rate)}` | `/ingestion` |
| 1 col (conditional) | StatusTile danger | Dead Letters | `{dead_letters}` | `/ingestion` |
| 1 col | StatusTile | Active Items | `{active_items}` | `/actions` |
| 1 col | StatusTile | Sources | `{enabled}/{total}` + green health dot | `/sources` |
| 1 col | StatusTile | Messenger | HealthBadge | `/messenger` |

The Dead Letters tile only appears when `dead_letters > 0`, collapsing the grid from 8 to 7 columns.

#### Signal Flow Card

Wrapped in a shadcn `Card` with:
- `CardHeader` (divided variant, `padding: 16px 20px`): mono section header "Signal Flow" + right-aligned subtitle "sources -> workbench -> outputs . hover to isolate" in mono 11px muted
- `CardContent` (padding `12px 16px`): `<SourceFlow>` component

#### Hot Feed + Signal Velocity (2-column)

`grid-cols-[1.6fr_1fr] gap-4` layout:
- Left: `HotFeed` card (preserved from current, with divided CardHeader)
- Right: Signal Velocity card containing:
  - CardHeader: divided, "Signal Velocity (24h)" section header
  - CardContent: Large mono number (24px bold) for total velocity count, then `<SmoothSparkline data={signalVelocityData} fill />` stretching to fill remaining height (min-height 72px)

#### Removed Elements

These are removed from Overview but their components remain in the codebase. Note that after this change, these components are **not rendered on any page** until a future stats/analytics page spec reintroduces them:

- `TopologyPanel` (Topology stays in `/src/components/Topology.tsx`, still used on Ingestion page or available for a future Infrastructure page)
- Ingestion area chart (ChartCard + Recharts AreaChart)
- Priority bar chart (ChartCard + Recharts BarChart)
- Source donut chart (ChartCard + Recharts PieChart)
- Category h-bar chart (ChartCard + Recharts BarChart)
- Recent Jobs DataTable
- `IngestionSuccessRate` StatCard tile (replaced by StatusTile in the strip)

#### Five UI State Taxonomy (Page-Level)

The existing Overview taxonomy gates are preserved and adapted:

| State | Trigger | Rendering |
|-------|---------|-----------|
| **Loading** | `overview.isPending` | Skeleton grid: 7-column skeleton strip (h-20), one large skeleton (h-72 for Sankey area), two-column skeleton row (h-48 each) |
| **Error** | `overview.isError` | Same error card as current: destructive text with message + request ID |
| **Empty** | All counts zero (`items.total === 0 && pending_triage === 0 && ...`) | Same EmptyState with "No activity yet" and "Add a source" CTA navigating to `/sources` |
| **Unauthorized** | Any query returns 401 | Same unauthorized card: "token unavailable" with tunnel advice |
| **Degraded** | Messenger not configured | Banner: amber-tinted border, `TriangleAlert` icon, "Messenger not configured -- triage cards are queued but unsent. Partial functionality." Positioned between the Signal Flow card and the Hot Feed row. |

#### Query Hooks Used

| Hook | Existing/New | Poll Interval |
|------|-------------|---------------|
| `useStatsOverview()` | Existing | 15s |
| `useFlowMatrix()` | New | 30s |
| `useMetricsTimeseries('signal_velocity', 24, 'hour')` | Existing | 60s |
| `useHotFeed()` | Existing | 15s |
| `useHealth()` | Existing (via TopBar SyncStatus) | 15s |
| `useMessenger()` | Existing | 60s |

Removed from Overview (no longer imported):
- `useIngestionTimeseries(14, 'day')`
- `useJobs(10)`
- `useTopology()`

---

## 5. Data Flow

### 5.1 New API Endpoint: `GET /api/stats/flow-matrix`

**File**: `src/workbench/api/stats.py`

**Route**: `@router.get("/flow-matrix")`

**Authentication**: Bearer token (inherited from global middleware, same as all `/api/stats/*` endpoints).

**Response Schema**:

```typescript
interface FlowMatrix {
  sources: Array<{
    id: string       // adapter_type (e.g., "phabricator.diff")
    label: string    // human-readable label (= adapter_type)
    vol: number      // total raw items enqueued from this source
  }>
  outputs: Array<{
    id: string       // "action_items" | "triage_queue" | "filtered_out" | "errors"
    label: string    // "Action Items" | "Triage Queue" | "Filtered Out" | "Errors"
    vol: number      // total items in this output bucket
  }>
  matrix: number[][] // matrix[i][j] = flow from sources[i] to outputs[j]
  rates: {
    ingestion_per_hour: number | null  // null when insufficient data
    egress_per_hour: number | null
  }
  window_hours: number | null  // null means "all time"
}
```

**Output order** is fixed: `[action_items, triage_queue, filtered_out, errors]`. This matters because the Sankey assigns specific colors and icons per output index.

**Handling of `manual` origin items**: The `ItemOrigin` enum includes `manual` (user-submitted items) in addition to `auto_included` and `triaged`. Manual items are **excluded from the flow matrix entirely**: they are not counted in any source's `vol` (which is derived from `ingestion_runs.raw_enqueued`, and manual items do not go through ingestion), and they are not counted in any output bucket. The `count_by_source_and_origin()` query returns rows for all three origins, but the flow matrix endpoint only reads the `auto_included` and `triaged` rows. This means the "Filtered Out" derivation (`vol - action - triage - errors`) remains accurate because `vol` (from ingestion runs) never included manual items in the first place. Manual items appear in the "Active Items" count on the status strip (via the existing `useStatsOverview()` endpoint) but are not part of the ingestion-to-output flow.

**Server-side query composition**:

```python
async def flow_matrix(request: Request):
    stores = request.app.state.stores

    # 1. Items by (source_type, origin) -- gives action_items + triage_queue
    #    Returns all origins including 'manual', but we only use
    #    'auto_included' and 'triaged' for the flow matrix (see above).
    by_source_origin = await stores.items.count_by_source_and_origin()

    # 2. Dead letters by source_type -- gives errors
    dead_by_source = await stores.ingestion_queue.count_dead_letters_by_source()

    # 3. Total raw enqueued by source -- gives source volumes
    #    This comes from ingestion_runs (pipeline-processed items only,
    #    never includes manual items).
    total_by_source = await stores.ingestion_runs.total_enqueued_by_source()

    # Enumerate all known source types (from ingestion-based data only;
    # manual items have no source in the ingestion pipeline)
    source_types = sorted(set(
        list(total_by_source.keys()) +
        [k[0] for k in by_source_origin.keys() if k[1] != "manual"] +
        list(dead_by_source.keys())
    ))

    sources = []
    matrix = []
    output_totals = [0, 0, 0, 0]  # action, triage, filtered, errors

    for st in source_types:
        vol = total_by_source.get(st, 0)
        action = by_source_origin.get((st, "auto_included"), 0)
        triage = by_source_origin.get((st, "triaged"), 0)
        # 'manual' origin is intentionally skipped -- see docstring above
        errors = dead_by_source.get(st, 0)
        filtered = max(0, vol - action - triage - errors)
        row = [action, triage, filtered, errors]
        matrix.append(row)
        sources.append({"id": st, "label": st, "vol": vol})
        for j in range(4):
            output_totals[j] += row[j]

    outputs = [
        {"id": "action_items", "label": "Action Items", "vol": output_totals[0]},
        {"id": "triage_queue", "label": "Triage Queue", "vol": output_totals[1]},
        {"id": "filtered_out", "label": "Filtered Out", "vol": output_totals[2]},
        {"id": "errors", "label": "Errors", "vol": output_totals[3]},
    ]

    # Rates
    ingestion_rate = await _compute_ingestion_rate(stores)
    egress_rate = await _compute_egress_rate(stores)

    return {
        "sources": sources,
        "outputs": outputs,
        "matrix": matrix,
        "rates": {
            "ingestion_per_hour": ingestion_rate,
            "egress_per_hour": egress_rate,
        },
        "window_hours": None,  # "all time" until a lookback is specified
    }
```

#### Rate Helper Functions

Two new private helper functions in `src/workbench/api/stats.py`:

```python
async def _compute_ingestion_rate(stores) -> float | None:
    """Average items ingested per hour across all ingestion runs.

    Computes SUM(raw_enqueued) / hours_elapsed where hours_elapsed is
    the time span from the earliest to latest ingestion run start.
    Returns None when there are fewer than 2 runs (cannot compute a rate
    from a single point) or when all runs have raw_enqueued=0.
    """
    row = await stores.ingestion_runs.pool.fetchrow(
        "SELECT COALESCE(SUM(raw_enqueued), 0) AS total, "
        "MIN(started_at) AS earliest, MAX(started_at) AS latest, "
        "COUNT(*) AS run_count "
        "FROM ingestion_runs WHERE status = 'success'"
    )
    if row["run_count"] < 2 or row["total"] == 0:
        return None
    hours = (row["latest"] - row["earliest"]).total_seconds() / 3600
    if hours < 0.01:  # avoid division by near-zero
        return None
    return round(row["total"] / hours, 1)


async def _compute_egress_rate(stores) -> float | None:
    """Items completed (egressed) per hour over the last 24 hours.

    Counts items with a completed_at timestamp in the last 24 hours
    and divides by 24 to get an hourly rate.
    Returns None when zero items were completed in the window.
    """
    row = await stores.items.pool.fetchrow(
        "SELECT COUNT(*) AS completed "
        "FROM items "
        "WHERE completed_at >= NOW() - INTERVAL '24 hours'"
    )
    completed = int(row["completed"])
    if completed == 0:
        return None
    return round(completed / 24, 1)
```

**Note**: These functions access the pool directly from the store instances. If the `items` store does not expose a `completed_at` column query, the egress rate function should use whichever completed-item count mechanism exists. The key contract is: egress = items finished in last 24h / 24, null when zero.

### 5.2 New Storage Layer Methods

#### 5.2.1 `ItemStore.count_by_source_and_origin()`

**Interface** (add to `src/workbench/storage/base.py` on `ItemStore`):

```python
@abstractmethod
async def count_by_source_and_origin(self) -> dict[tuple[str, str], int]:
    """COUNT(*) GROUP BY source_type, origin."""
    ...
```

**PostgreSQL implementation** (add to `src/workbench/storage/postgres/items.py`):

```sql
SELECT source_type, origin, COUNT(*) FROM items
GROUP BY source_type, origin
```

Returns `{("phabricator.diff", "auto_included"): 150, ("phabricator.diff", "triaged"): 230, ...}`.

#### 5.2.2 `IngestionQueueStore.count_dead_letters_by_source()`

**Interface** (add to `src/workbench/storage/base.py` on `IngestionQueueStore`):

```python
@abstractmethod
async def count_dead_letters_by_source(self) -> dict[str, int]:
    """COUNT(*) FROM ingestion_queue WHERE status='dead_letter' GROUP BY source_type."""
    ...
```

**PostgreSQL implementation** (add to `src/workbench/storage/postgres/ingestion_queue.py`):

```sql
SELECT source_type, COUNT(*) FROM ingestion_queue
WHERE status = 'dead_letter'
GROUP BY source_type
```

The `ingestion_queue` table has both `source_type` and `status` columns with indexes. This is the same table already queried by `count_by_source()` (which counts only in-flight).

#### 5.2.3 `IngestionRunStore.total_enqueued_by_source()`

**Interface and implementation** (add to `src/workbench/storage/ingestion_runs.py`, which contains both the abstract `IngestionRunStore` class and the `PgIngestionRunStore` implementation in the same file):

Abstract method on `IngestionRunStore`:

```python
@abstractmethod
async def total_enqueued_by_source(self) -> dict[str, int]:
    """SUM(raw_enqueued) per source adapter_type via source_configs join."""
    ...
```

Implementation on `PgIngestionRunStore`:

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

This join is necessary because `ingestion_runs` uses `source_id` (the source config UUID), not the `adapter_type` string.

### 5.3 Frontend Hook: `useFlowMatrix()`

**File**: `ui/src/hooks/useStats.ts`

**Type definition** (co-located with existing stats types):

```typescript
export interface FlowMatrixSource {
  id: string
  label: string
  vol: number
}

export interface FlowMatrixOutput {
  id: string
  label: string
  vol: number
}

export interface FlowMatrix {
  sources: FlowMatrixSource[]
  outputs: FlowMatrixOutput[]
  matrix: number[][]
  rates: {
    ingestion_per_hour: number | null
    egress_per_hour: number | null
  }
  window_hours: number | null
}
```

**Hook**:

```typescript
export function useFlowMatrix() {
  return useQuery({
    queryKey: ['stats', 'flow-matrix'],
    queryFn: () => apiGet<FlowMatrix>('/api/stats/flow-matrix'),
    refetchInterval: pollWhenVisible(30_000),
  })
}
```

Poll interval: 30 seconds (matches `useSourcesRollup`). Flow volumes change slowly; 15-second polling would be wasteful.

### 5.4 Source-to-Icon Mapping

The SourceFlow assigns a color and lucide icon to each source. The prototype hardcodes four sources. The production version must handle dynamic sources from the API. The mapping:

```typescript
const SOURCE_STYLES: Record<string, { color: string; icon: string }> = {
  'phabricator.diff': { color: '#ff6a2b', icon: 'GitPullRequest' },
  'google_chat':      { color: '#9ad08a', icon: 'MessageCircle' },
  'github':           { color: '#ff6a2b', icon: 'Github' },
  'email':            { color: '#71d2ff', icon: 'Mail' },
  'calendar':         { color: '#ffb59a', icon: 'Calendar' },
  'chat':             { color: '#9ad08a', icon: 'MessageCircle' },
}

const FALLBACK_COLORS = ['#ff6a2b', '#71d2ff', '#ffb59a', '#9ad08a', '#ba8aff', '#353438']
```

Unknown source types get a color from the fallback palette (cycling by index) and the `Database` icon. This is consistent with the `CHART_PALETTE` ordering from `chart-theme.ts`.

---

## 6. Brand / Chrome Updates

### 6.1 Sidebar Rail WB Icon

**File**: `ui/src/components/AppSidebar.tsx`

Add a WB icon button at the top of the rail nav, above the first nav item, matching the prototype's `wb-rail-logo`:

```tsx
<button
  className="mb-3 inline-flex size-9 shrink-0 items-center justify-center rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
  onClick={() => navigate('/')}
  aria-label="WorkBench home"
  title="WorkBench"
>
  <img src="/wb-icon.svg" alt="WorkBench" width={36} height={36} className="block" />
</button>
```

This goes before the `<TooltipProvider>` block. The button uses `navigate('/')` via the React Router `useNavigate` hook. The icon is the same 36x36 display as the prototype.

### 6.2 TopBar Wordmark Update

**File**: `ui/src/components/TopBar.tsx`

Replace the current brand mark (a solid orange square with "W" + "Workbench" text) with:

```tsx
<button
  onClick={() => navigate('/')}
  aria-label="WorkBench home"
  className="flex items-center gap-2 bg-transparent border-0 p-0 cursor-pointer"
>
  <img src="/wb-icon.svg" alt="" width={28} height={28} className="block" />
  <span className="font-display text-[15px] tracking-tight text-foreground">
    <span className="font-bold">Work</span>
    <span className="font-bold text-primary">B</span>
    <span className="font-medium">ench</span>
  </span>
</button>
```

Key typographic details from the prototype (`shell.jsx` TopBar):
- Font: `var(--font-display)` (Space Grotesk Variable)
- Size: 15px
- Letter-spacing: `-0.01em`
- "Work": `font-weight: 700`
- "B": `font-weight: 700, color: var(--primary)` (#ff6a2b)
- "ench": `font-weight: 500`

The button wraps both icon and wordmark to make the entire unit clickable for home navigation.

---

## 7. Testing Strategy

### 7.1 Unit Tests

| File | Tests |
|------|-------|
| `ui/src/components/SmoothSparkline.test.tsx` | (1) empty data renders em-dash, (2) single point renders dot, (3) multi-point renders SVG with path, (4) fill mode sets height to 100%, (5) all states render `aria-hidden="true"`, (6) `toCoordinates` produces correct [x, y] pairs for known input |
| `ui/src/components/StatusTile.test.tsx` | (1) renders label and value, (2) onClick fires navigation, (3) danger variant applies destructive styling, (4) arrow icon appears on hover, (5) StatusTilePrimary renders pending count and P0 count, (6) StatusTile renders when value is a string like 'n/a' (null-handled by caller) |
| `ui/src/components/SourceFlow.test.tsx` | (1) loading state renders skeleton, (2) error state renders error card with retry button (not ChartCard pattern), (3) empty data renders zero-width ribbons, (4) normal data renders correct number of source/output nodes, (5) `aria-label` present on SVG, (6) output click fires onNavigate, (7) `prefers-reduced-motion: reduce` hides dots |
| `ui/src/pages/Overview.test.tsx` | Update existing tests: (1) loading skeleton has new structure (status strip skeleton + Sankey skeleton), (2) empty state unchanged, (3) unauthorized state unchanged, (4) error state unchanged, (5) normal state renders StatusTilePrimary with triage count, (6) normal state renders SourceFlow card, (7) dead letter tile conditionally appears, (8) no Recharts charts or Recent Jobs table rendered, (9) no TopologyPanel rendered |
| `ui/src/hooks/useStats.test.ts` | Add: (1) `useFlowMatrix` returns typed FlowMatrix, (2) poll interval is 30s, (3) query key is `['stats', 'flow-matrix']` |

### 7.2 Server Tests

Tests are added to existing test files that follow the codebase's established naming convention:

| File | Tests |
|------|-------|
| `tests/test_stats_api.py` (existing file) | Add: (1) `GET /api/stats/flow-matrix` returns 200 with correct shape, (2) sources list matches configured sources, (3) matrix rows sum to source volumes, (4) output order is fixed [action_items, triage_queue, filtered_out, errors], (5) rates are null when no ingestion runs exist, (6) empty state returns empty sources/matrix/zero-vol outputs, (7) manual-origin items are excluded from flow matrix |
| `tests/test_storage.py` (existing file) | Add to existing storage test file: (1) `count_by_source_and_origin` returns correct grouping, (2) `count_by_source_and_origin` handles empty table, (3) `count_dead_letters_by_source` returns only dead_letter status, (4) `count_dead_letters_by_source` handles no dead letters, (5) `total_enqueued_by_source` correctly joins to source_configs, (6) `total_enqueued_by_source` handles no runs |

### 7.3 Integration / Visual Tests

- Verify the SourceFlow animation runs at 60fps with 4 sources and 80 dots (performance test with `requestAnimationFrame` timing)
- Verify hover cross-proportioning transitions complete within 280ms
- Verify the status strip is responsive: at `< 768px`, tiles should stack (implementation detail: the grid should use `grid-cols-2 md:grid-cols-4 lg:grid-cols-7` or similar responsive breakpoints)
- Verify the WB icon SVG renders correctly in both light and dark themes
- Verify the TopBar wordmark shows the orange "B" in both themes

### 7.4 Accessibility Tests

- SourceFlow SVG has `role="img"` and meaningful `aria-label`
- All StatusTile buttons have accessible names (the label text serves as the accessible name via button content)
- Keyboard navigation: all tiles are focusable and activatable with Enter/Space
- Focus rings: all tiles and the WB icon button show `outline: 2px solid var(--ring)` on focus-visible
- Reduced motion: dots hidden, transitions disabled

---

## 8. Migration Notes

### 8.1 Incremental Delivery Order

The work should be delivered in vertical slices. Each slice is independently deployable:

**Slice A: Storage + API** (backend only, no frontend changes)
1. Add three abstract methods to storage interfaces
2. Add PostgreSQL implementations
3. Add `flow_matrix` endpoint to `stats.py` with `_compute_ingestion_rate` and `_compute_egress_rate` helpers
4. Add server tests
5. Run `make up` to verify

**Slice B: SmoothSparkline + StatusTile** (new components, not wired to pages yet)
1. Create `SmoothSparkline.tsx` with `toCoordinates` mapping and tests
2. Create `StatusTile.tsx` and `StatusTilePrimary.tsx` with tests
3. These are leaf components with no API dependencies

**Slice C: Brand assets** (independent of other slices)
1. Copy SVG assets to `ui/public/`
2. Update `AppSidebar.tsx` to add WB icon
3. Update `TopBar.tsx` wordmark
4. Update tests

**Slice D: SourceFlow component** (depends on Slice A for types)
1. Add `FlowMatrix` types and `useFlowMatrix()` hook to `useStats.ts`
2. Create `SourceFlow.tsx` with full animation, hover, and state handling
3. Add component tests

**Slice E: Overview page rewrite** (depends on all above)
1. Rewrite `Overview.tsx` to use new layout
2. Update `Overview.test.tsx`
3. Remove unused imports (Recharts charts, Topology, DataTable from Overview)

### 8.2 Files Created

| File | Purpose |
|------|---------|
| `ui/src/components/SourceFlow.tsx` | Animated SVG Sankey component |
| `ui/src/components/SmoothSparkline.tsx` | Catmull-Rom sparkline component |
| `ui/src/components/StatusTile.tsx` | Exports `StatusTile` and `StatusTilePrimary` |
| `ui/src/components/SourceFlow.test.tsx` | SourceFlow tests |
| `ui/src/components/SmoothSparkline.test.tsx` | SmoothSparkline tests |
| `ui/src/components/StatusTile.test.tsx` | StatusTile tests |
| `ui/public/wb-icon.svg` | WB brand icon |
| `ui/public/wb-primary-lockup.svg` | WB full wordmark lockup |

### 8.3 Files Modified

| File | Change |
|------|--------|
| `ui/src/pages/Overview.tsx` | Full rewrite of page layout |
| `ui/src/pages/Overview.test.tsx` | Updated assertions for new layout |
| `ui/src/hooks/useStats.ts` | Add `FlowMatrix` types + `useFlowMatrix()` hook |
| `ui/src/components/AppSidebar.tsx` | Add WB icon button at top of rail |
| `ui/src/components/TopBar.tsx` | Replace brand mark with icon + split wordmark |
| `src/workbench/api/stats.py` | Add `/flow-matrix` endpoint + `_compute_ingestion_rate` and `_compute_egress_rate` helpers |
| `src/workbench/storage/base.py` | Add 2 abstract methods (ItemStore, IngestionQueueStore) |
| `src/workbench/storage/ingestion_runs.py` | Add 1 abstract method on `IngestionRunStore` + implementation on `PgIngestionRunStore` (both classes live in this single file) |
| `src/workbench/storage/postgres/items.py` | Add `count_by_source_and_origin()` implementation |
| `src/workbench/storage/postgres/ingestion_queue.py` | Add `count_dead_letters_by_source()` implementation |
| `tests/test_stats_api.py` | Add flow-matrix endpoint tests |
| `tests/test_storage.py` | Add tests for three new storage methods |

### 8.4 Files NOT Modified

- `ui/src/components/Sparkline.tsx` -- Preserved for other pages. Not deleted.
- `ui/src/components/StatCard.tsx` -- Preserved for other pages. Not used on Overview anymore.
- `ui/src/components/ChartCard.tsx` -- Preserved for the future stats page.
- `ui/src/components/Topology.tsx` -- Preserved per ADR 0041. Just no longer imported in Overview.
- `ui/src/components/DataTable.tsx` -- Preserved for other pages.
- `ui/src/index.css` -- No token changes. Accent stays #ff6a2b, radius stays 6px, no density attributes added.
- `ui/src/lib/chart-theme.ts` -- No changes. SourceFlow uses its own inline colors for output nodes because those colors are semantic (action=purple, triage=purple, filter=gray, error=red) and fixed, not categorical chart series that cycle through a palette. Contrast certification for these colors against the `#0e0e11` card surface is documented in Section 3.1.

### 8.5 No Database Migrations Required

The three new storage methods are read-only aggregate queries over existing tables and columns (`items.source_type`, `items.origin`, `ingestion_queue.source_type`, `ingestion_queue.status`, `ingestion_runs.source_id`, `ingestion_runs.raw_enqueued`, `source_configs.adapter_type`). No schema changes. No Alembic migration.

### 8.6 Performance Considerations

- The `/flow-matrix` endpoint runs three SQL aggregate queries plus two rate queries. Each aggregate is a single-table `COUNT(*) GROUP BY` (or `SUM ... GROUP BY` with one join). All columns have existing indexes. Expected latency: < 50ms.
- The SourceFlow animation runs an 80-dot pool via `requestAnimationFrame`. Each frame updates at most 80 circle positions using `getPointAtLength()`. This is well within the budget for 60fps on any modern browser. The `useEffect` cleanup cancels the animation frame on unmount.
- The flow matrix hook polls every 30 seconds. Combined with the existing hooks, the Overview page makes approximately 6 API calls per poll cycle, which is acceptable for a single-user tool.

### 8.7 Design Prototype Files Not Ported

These prototype files are design-time scaffolding and are NOT ported:

| File | Reason |
|------|--------|
| `tweaks.jsx` / `tweaks-panel.jsx` | Excluded per resolved decision 1 |
| `data.js` | Mock data for prototype rendering |
| `main.jsx` | Prototype entry point with Babel/React CDN loading |
| `shell.jsx` | Prototype shell (production already has AppShell.tsx) |
| `primitives.jsx` | Prototype primitives (production already has shadcn components) |
| `app.css` | Prototype styles; production uses Tailwind utilities. StatusTile hover/focus styles are implemented as Tailwind classes. |
| All other `page-*.jsx` files | Only Overview is being redesigned; other pages are unchanged |