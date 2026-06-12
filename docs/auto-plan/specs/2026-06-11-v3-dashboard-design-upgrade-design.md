Now I have comprehensive understanding of the codebase. Let me produce the updated spec with all issues fixed and suggestions incorporated.

# WorkBench v3 Dashboard Design Upgrade -- Design Specification

## Overview

WorkBench v3 is a major dashboard redesign that adds three new pages (Ingestion Funnel, Search, Feedback System), introduces a feedback correction data store, restructures navigation (hover-expand rail, breadcrumbs, consolidated Settings sub-tabs), and modifies six existing pages. The upgrade implements a closed-loop learning system where user corrections to filter classifications generate tuning tasks, refine prompts, and improve noise filtering over time.

The design prototype at `/tmp/design_v3/workbench/` is the canonical visual reference. All settled ADRs (0033/0034/0035/0036/0038/0046) remain unchanged. The stack remains React 19 + TypeScript + Vite + shadcn/ui + Tailwind v4 + TanStack Query + Recharts + HashRouter.

**ADR cross-references:** ADR 0033 (theme tokens) -- all new components use CSS custom properties from the existing token system. ADR 0034 (typography/theme) -- text styles follow the established scale. ADR 0035 (self-hosted fonts) -- no new font dependencies. ADR 0036 (icon rail navigation) -- v3 extends the 64px rail with hover-expand behavior; preserves `aria-current="page"`, Radix tooltips, and the CSS grid shell. ADR 0038 (chart theme) -- MultiLineChart and SourceFlow import from `lib/chart-theme.ts`. ADR 0046 (contrast contract) -- orange-on-dark contrast ratios preserved for all new colored elements.

---

## Scope

### In Scope

**New pages:**
- Ingestion Funnel (`/filters`) -- interleaved enrichers, filters, loopbacks with reordering, per-item funnel traces, correction feedback, and auto-tuning
- Search (`/search`) -- full corpus search with master/detail layout, contextual payload renderers, processing log, item actions
- Feedback System -- runtime store for filter corrections, auto-tuning tasks surfaced on Action Items page

**Changed pages:**
- Overview -- clickable Hot Feed items opening ItemFunnelDialog, SourceFlow Sankey replacing or augmenting Topology, stalled source indicators
- Triage -- estimated priority badges with "est" prefix + tooltip, focus-by-theme filter panel, card summary click-through to ItemFunnelDialog
- Action Items -- Work Mode removed, MultiLineChart throughput (incoming vs completion), FilterTuningCard section from feedback store
- Ingestion -- Live Funnel Tail (structured streaming table), queue stats promoted to top-level cards, dead letters promoted, IngestionFunnel embedded at bottom
- Settings -- sub-tabs (System / Sources / Messenger) via Radix Tabs + React Router hybrid pattern (see Decision: Settings Tab Routing)
- Shell -- hover-expand rail with labels, breadcrumbs on every page, nav restructure (Search added at position 2; Sources + Messenger removed from rail)

**Cross-cutting:**
- Portal component for dialog centering
- useFeedbackStore() hook for filter corrections
- ItemFunnelDialog reused across Overview, Triage, Ingestion, Search
- MultiLineChart component (custom SVG, Catmull-Rom smoothing)
- SourceFlow animated Sankey component
- Estimated priority vs user-set priority distinction
- ActionChip, ConfidenceBar, VerdictPill, StateDot, SectionHeader shared components
- Funnel constants module (`lib/funnel-constants.ts`)

### Out of Scope

- Tweaks panel (design-time only, excluded from production)
- WebSocket real-time updates (single-user tool; polling is sufficient)
- SourceFlow Sankey as a separate branch if complexity warrants it
- Full E2E test suite (unit + component + integration tests only in initial branches)
- OpenAPI type generation changes (hooks define their own interfaces)
- Server-side prompt auto-application pipeline (only the API endpoint to persist patches)

---

## Decisions

### Decision: SourceFlow Flow Matrix Is Client-Computed (Resolves Contradiction)

The SourceFlow flow matrix is computed **client-side** from existing stats endpoints (`useSourcesRollup` + `useStatsOverview` + `useQueueStats`). There is no `GET /api/flow-matrix` endpoint. The flow matrix maps source volumes to output buckets (triaged/dropped/pending/action) using the source rollup `items_stored` counts proportioned against the global `items.by_status` breakdown. This avoids new backend work and aligns with the principle that the SourceFlow is a visualization layer over existing data. The `flows` prop on `<SourceFlow>` is produced by a pure function `buildFlowMatrix(sources, stats, queue)` in `lib/funnel-helpers.ts`.

### Decision: Settings Tabs Use Hybrid Radix + React Router Pattern

Settings uses Radix UI Tabs for accessible keyboard navigation, focus management, and styling (TabsList/TabsTrigger/TabsContent), but the active tab state is **derived from `window.location.pathname`** via React Router. Clicking a `TabsTrigger` calls `navigate('/settings/sources')` instead of relying on Radix internal state. The Radix `value` prop is set to the path segment (`pathname.split('/')[2] || 'system'`), making it a controlled component driven by the URL. This gives URL-addressable tabs (shareable deep links, browser back/forward) with Radix's accessibility guarantees (arrow key navigation between triggers, `role=tablist`/`role=tab`/`aria-selected`).

### Decision: Filter Correction Undo Semantics

Clicking "undo" on a FunnelStage correction calls `removeOverride(itemId, filterId)` which (1) deletes the `FeedbackOverride` record from both client store and server, and (2) dismisses the associated `FilterTuningTask` if its status is `open`. If the tuning task was already `applied` (prompt was auto-applied), the undo shows a confirmation dialog: "This correction's prompt update was already applied. Undoing the correction will not revert the applied prompt change. Continue?" with Cancel/Undo buttons. The applied prompt remains in effect -- reverting auto-applied prompts requires manual editing via the FilterDetailDialog.

### Decision: Per-Item Loop Count Tracking

Loop count per item is tracked as a **session-only field** on the `FunnelItem` type: `loop_count: number` (default 0). The server increments this counter each time a loop-back stage re-injects the item, and includes it in the `GET /api/funnel/items` and `GET /api/items/{itemId}/funnel` responses. The counter is stored in the `items.funnel_log` JSONB column alongside stage records (as a top-level `loop_count` key in the JSON), not as a separate database column. The `LoopBack.max_loops` guard compares against this counter server-side before re-injection.

### Decision: Search Page Keyboard Navigation Is Required

Arrow up/down to navigate result list, Enter to select/open, Escape to clear selection and return focus to search input. This is required for WCAG 2.1 AA compliance (keyboard operability), not optional. The result list uses `role="listbox"` with `role="option"` on each `ResultRow`, and `aria-activedescendant` on the container tracks the focused item.

---

## Five-State UI Taxonomy

All pages and major components document five UI states for consistency. The five states are: **loading**, **error**, **empty**, **unauthorized**, and **degraded**.

### FiltersPage (`/filters`)

| State | Trigger | Rendering |
|---|---|---|
| Loading | Initial fetch of filter rules, enrichers, loopbacks | Skeleton cards (3 placeholder cards with pulsing backgrounds, matching card height) |
| Error | API error on any of the three fetches | Alert banner: "Failed to load funnel configuration" with error message, request ID, and "Retry" button |
| Empty | All three arrays empty (no rules, no enrichers, no loopbacks configured) | Centered empty state: dashed border card, "No funnel stages configured. Add a filter rule to get started." with "Add filter" primary button |
| Unauthorized | 401/403 from API | Full-page lockout (reuses existing Overview unauthorized pattern): "Session expired" with re-authenticate link |
| Degraded | One of the three fetches fails but others succeed (e.g., enrichers endpoint returns 500 but filters load) | Render available sections normally; failed section shows inline warning: "Enricher data unavailable" with retry link. Funnel ordering omits the failed kind. |

### LiveTail

| State | Trigger | Rendering |
|---|---|---|
| Loading | Initial fetch of funnel items | Skeleton rows (5 rows with pulsing placeholders in 5-column grid) |
| Error | `useFunnelItems` returns error, or connection to polling endpoint lost | Inline alert inside the 226px container: "Connection lost -- retrying..." with animated spinner. Auto-retries via TanStack Query retry policy. |
| Empty | `funnelItems` array is empty (no recent items processed) | Centered in container: "No recent items. Items will appear here as they flow through the funnel." with muted text |
| Paused | User clicks pause toggle | Static table with last-known rows, animated pulse dot stops, toggle label changes to "Paused". Header shows "Paused" badge. No new rows stream in. |
| Degraded | Polling interval missed (> 3x expected interval without data) | Stale-data indicator: amber dot next to "Live" label, tooltip "Data may be stale -- last update {relative time}" |

### SourceFlow

| State | Trigger | Rendering |
|---|---|---|
| Loading | `useSourcesRollup` or `useStatsOverview` loading | Placeholder: gray dashed outlines of source nodes, center module, and output nodes with pulsing opacity animation |
| Error | Stats fetch fails | Inline alert below placeholder: "Flow data unavailable" with error message and "Retry" button. No Sankey paths rendered. |
| Empty | No sources configured (`sources.length === 0`) | Centered: "No sources configured. Add sources in Settings to see data flow." with link to `/settings/sources` |
| Unauthorized | 401/403 | Handled at page level (SourceFlow is embedded in Overview, which handles auth) |
| Degraded | Some sources have `health_status === 'erroring'` but others are healthy | Healthy sources render normally. Erroring sources show red dashed ribbons, TriangleAlert icon, and "STALLED" label. Flow volumes for stalled sources show last-known values with "(stale)" suffix. |

---

## Components

### New Components

#### Shared Primitives

| Component | File | Props | Purpose |
|---|---|---|---|
| `Portal` | `components/Portal.tsx` | `children: ReactNode` | Simple `ReactDOM.createPortal` wrapper rendering `children` into `document.body`. No additional logic, state, or styling. Used by dialogs that need to escape parent overflow/z-index stacking. |
| `SectionHeader` | `components/SectionHeader.tsx` | `children: ReactNode`, `right?: ReactNode` | Mono uppercase micro-label (`text-xs font-mono uppercase tracking-wide text-muted-foreground`) with optional `right` slot for inline controls. |
| `ActionChip` | `components/ActionChip.tsx` | `action: StageOutcome`, `label?: string`, `confidence?: number`, `small?: boolean` | Color-coded inline chip for filter actions. Uses `STAGE_META` from `lib/funnel-constants.ts` for colors/icons. Shows confidence percentage when provided. Label text per action: `drop` = "Drop", `include` = "Include", `label` = "Label: {label}", `context` = "Add context", `pass` = "Pass", `skip` = "Skip", `loopback` = "Loop back". |
| `ConfidenceBar` | `components/ConfidenceBar.tsx` | `value: number` (0-100) | Horizontal progress bar with percentage label. Colors: green >= 90, primary >= 80, brand otherwise. Includes `aria-valuenow/valuemin/valuemax`. |
| `VerdictPill` | `components/VerdictPill.tsx` | `verdict: Verdict`, `large?: boolean` | Final verdict indicator. Colors: queued=tertiary, dropped=red, triaged=green. Renders `decision` text always. If `verdict.priority` is non-null, renders priority badge with value; if null/undefined, omits priority badge entirely (shows decision + confidence only). Confidence shown as percentage suffix. |
| `StateDot` | `components/StateDot.tsx` | `state: ItemState` | Small colored dot + label for item state. Colors: triaged=green, pending_triage=tertiary, action_item=primary, dropped=red, archived=muted. |
| `SourceChip` | `components/SourceChip.tsx` | `name: string` | Inline source icon + name chip. Uses `SRC_ICON` mapping (github->Github, email->Mail, calendar->Calendar, chat->MessageCircle, phabricator->FileCode). |
| `Breadcrumb` | `components/Breadcrumb.tsx` | (reads route from React Router) | Route-driven back navigation. Renders `< Back to {label}` button in mono uppercase (11px, .04em tracking). Hidden at `/` (root). Route mapping table below. Renders inside `wb-main-inner` with 12px bottom margin. |

**Breadcrumb Route Mapping:**

| Current Route Pattern | Back Target | Back Label |
|---|---|---|
| `/` | (hidden) | -- |
| `/triage/:id` | `/triage` | "Triage" |
| `/triage` | `/` | "Overview" |
| `/filters` | `/` | "Overview" |
| `/search` | `/` | "Overview" |
| `/settings` | `/` | "Overview" |
| `/settings/sources` | `/settings` | "Settings" |
| `/settings/messenger` | `/settings` | "Settings" |
| `/sources` | `/` | "Overview" |
| `/messenger` | `/` | "Overview" |
| `/knowledge` | `/` | "Overview" |
| `/ingestion` | `/` | "Overview" |
| `/actions` | `/` | "Overview" |

#### Funnel Components

| Component | File | Purpose |
|---|---|---|
| `FunnelStage` | `components/funnel/FunnelStage.tsx` | Single stage in an item's funnel trace. Vertical timeline layout with colored circle icon, connecting line, stage number, filter ID, ActionChip showing outcome (or corrected outcome with strikethrough), weak/below-threshold indicator, timing info (absolute + relative + duration), quoted prompt text (uses patched prompt from feedback store if applied), reason text, context bubble, "correct" button opening correction picker ("This should have been..." with outcome choices: Keep/include, Drop, Label spam, No action), feedback receipt card after correction, and "undo" for existing corrections (see Decision: Filter Correction Undo Semantics). Stage visual treatment varies by kind: enricher stages use tertiary (teal) border and enricher icon, filter stages use brand color border, loopback stages use primary color border. Kind is detected via `filterId` lookup against the enrichers/filters/loopbacks arrays from funnel context. **Timing fallback:** when `timing` or `baseTime` props are null, the timing row is omitted entirely -- only filterId, outcome, reason, and context are rendered. No "timing unavailable" placeholder is shown. Props: `stage`, `index`, `isLast`, `item`, `editable`, `timing?`, `baseTime?`. |
| `ItemFunnelDialog` | `components/funnel/ItemFunnelDialog.tsx` | Full per-item provenance modal. Header: source icon, item ID, timestamp, summary, VerdictPill. Treatment log: enricher count + filter count + total processing time, followed by all FunnelStage components. Aggregated verdict section: LLM-joined verdict with confidence scores, merged arrow to VerdictPill, rationale text, carried-forward context. Uses `itemLog(item)` to synthesize enricher stages and `stageTimings(log)` for timing. Props: `item: FunnelItem` (non-nullable -- see mounting pattern below), `onClose: () => void`. Uses existing Dialog primitive. Focus trap, Escape-to-close, `aria-modal`, `aria-labelledby`. |
| `FilterRuleCard` | `components/funnel/FilterRuleCard.tsx` | Ordered filter card in the funnel. Left rail with order number + up/down arrows. Colored left border by action type (brand color). ActionChip + rule ID + "tuned" indicator. Quoted prompt. "Applies to" SourceChips. ConfidenceBar. Origin badge + processed count. Switch toggle + kebab menu (view items, edit prompt, enable/disable, delete). Props: `rule`, `order`, `total`, `onToggle`, `onDelete`, `onMove`, `onOpen`, `reorderable`. |
| `FilterDetailDialog` | `components/funnel/FilterDetailDialog.tsx` | Shows items processed by a filter rule with corrections summary. Header: ActionChip, rule ID, prompt text (shows "auto-tuned" if feedback patched). Correction summary box when corrections exist. Scrollable table: Item ID, summary, source, "This rule did" column with correction indicator, final verdict. Row click opens ItemFunnelDialog. Props: `rule`, `onOpenItem`, `onClose`. |
| `EnricherCard` | `components/funnel/EnricherCard.tsx` | Enricher stage card. Teal (tertiary) left border + "enricher" badge with tertiary background. Source icon + label + ID + depth badge (shallow/deep). "Adds context" row: field chips. "Records to memory" row: entity chips. Budget row: max calls, max time, avg time. Stats: enriched count. Props: `enricher`, `order`, `total`, `onToggle`, `onMove`, `onOpen`, `reorderable`. |
| `EnricherDetailDialog` | `components/funnel/EnricherDetailDialog.tsx` | Enrichment samples for an enricher. Header: enricher badge, label, ID, stats. Sample cards: item ID, summary, context k/v chips, recorded entities. Props: `enricher`, `onClose`. |
| `LoopBackCard` | `components/funnel/LoopBackCard.tsx` | Loop-back control stage card. Primary-colored left border + "loop-back" badge. Label + ID + "max N x" badge. Trigger description. "Re-injects to" row. Condition text. Guard: max loops. Stats: looped count + avg loops. Props: `lb`, `order`, `total`, `onToggle`, `onMove`, `reorderable`. |
| `AddRuleDialog` | `components/funnel/AddRuleDialog.tsx` | Create a new natural-language filter rule. Fields: Prompt (textarea), Action (drop/include/label select), Source (github/email/calendar/chat/all). Explicitly states "the noise filter matches it with the LLM, not regex." Props: `open`, `onClose`, `onCreate`. |

#### Chart Components

| Component | File | Purpose |
|---|---|---|
| `MultiLineChart` | `components/MultiLineChart.tsx` | Multi-series smooth SVG line chart with Catmull-Rom curves, dashed grid lines, HTML axis overlay for undistorted labels, and interactive hover tooltip with vertical rule + per-series dots. **Tooltip flip logic:** tooltip renders on the right of the hover point by default; flips to the left when the hovered point's x coordinate exceeds `containerWidth * 0.75` OR when the tooltip's right edge would extend beyond the container's right edge minus 40px padding. Legend row below. Props: `series[]` ({name, color, data[]}), `height` (default 132), `xLabels[]`. Imports colors from `lib/chart-theme.ts`. |
| `SourceFlow` | `components/SourceFlow.tsx` | Animated Sankey-style flow visualization. Left column = 4 input sources with per-day volume. Center = WorkBench module showing IN/h and OUT/h. Right column = 4 output buckets. Bezier ribbon paths, rAF-driven animated dots. **Animation parameters:** 80-dot object pool; each dot traverses source-to-output in 2.8s duration; spawn rate is 1 dot per 10 items/day of flow volume (e.g., a source with 100 items/day spawns 10 dots/s); dots are recycled back to the pool when they reach the output node; animation pauses when `document.hidden === true` (Page Visibility API) and resumes on `visibilitychange`. Stalled source detection (red dashed ribbons + TriangleAlert when `health_status === 'erroring'`). **Hover re-proportioning:** hovering a source node zeros non-hovered source ribbons and re-proportions output ribbons by the hovered source's flow only; hovering an output node zeros non-hovered output ribbons and re-proportions input ribbons by the hovered output's flow. All transitions use CSS `transition: 300ms ease`. Click navigation for outputs. **Flow matrix is client-computed** from `useSourcesRollup` + `useStatsOverview` + `useQueueStats` via `buildFlowMatrix()` (see Decision: SourceFlow Flow Matrix). Props: `sources` (SourceRollup[]), `stats` (StatsOverview), `queue` (QueueStats), `onNavigate` callback. Uses `CHART_COLORS` from `lib/chart-theme.ts`. Respects `prefers-reduced-motion`. Includes visually-hidden table fallback for screen readers. |

#### Filter Tuning

| Component | File | Purpose |
|---|---|---|
| `FilterTuningCard` | `components/FilterTuningCard.tsx` | Card showing a pending filter-tuning task. "filter tuning" badge with Sparkles icon, filter ID, description of reclassification, proposed prompt section, two actions: "Auto-apply update" (primary) and "I'll do it manually" (ghost). Props: `task`, `onApply`, `onDismiss`. |

#### Live Tail

| Component | File | Purpose |
|---|---|---|
| `LiveTail` | `components/LiveTail.tsx` | Auto-scrolling structured table for the ingestion funnel. 5-column grid: Time, Item ID, Source, Funnel stage (filter/enricher ID + action), Status (ActionChip). Fixed-height (226px) scrollable area. Rows stream in at ~2.1s intervals via `setInterval`. Flattens `funnelItems` into item+stage event pool via `itemLog()`. Max 60 rows. Newest row gets `wb-tail-new` CSS class for flash animation. Enricher stages in tertiary color, filter stages in brand color, loopback stages in primary color. Click row to open ItemFunnelDialog. Props: `onOpenItem` callback, `paused` boolean. Includes live/paused toggle button with animated pulse dot. See Five-State UI Taxonomy section for loading/error/empty/paused/degraded states. |

#### Search Page Sub-components

| Component | File | Purpose |
|---|---|---|
| `ResultRow` | `components/search/ResultRow.tsx` | Clickable result card. Kind icon (lucide), item ID (mono), priority badge, StateDot, summary text, footer with source + relative time + relevance score percentage. Props: `item`, `active` boolean, `onClick`. Active state = selection highlighting. |
| `SearchItemDetail` | `components/search/SearchItemDetail.tsx` | Full detail view for selected item. (1) Header: kind icon, ID, priority badge, StateDot, source, timestamp, summary, tags. (2) Actions bar: priority select, Mark done, Snooze 4h, Archive, Delete. (3) "Why this matters to you" section with LLM summary (Sparkles icon + "LLM" label). (4) Contextual payload card using ItemContext dispatcher. (5) Processing log using FunnelStage components + VerdictPill + rationale. Empty state when no item selected: dashed border, "select an item to inspect its full processing log." Props: `item`, `onAction(id, action, value)`. |
| `DiffContext` | `components/search/contextual/DiffContext.tsx` | Author, team, status badge, Phabricator link, DiffHunks (max 15). Props: `ctx`. |
| `EmailContext` | `components/search/contextual/EmailContext.tsx` | From/to/when definition list, pre-formatted body text. Props: `ctx`. |
| `MeetingContext` | `components/search/contextual/MeetingContext.tsx` | When/where/attendees definition list, agenda block (or "no agenda posted" warning). Props: `ctx`. |
| `ChatContext` | `components/search/contextual/ChatContext.tsx` | Channel name, message list with author/text/timestamp per message. Props: `ctx`. |
| `ItemContext` | `components/search/contextual/ItemContext.tsx` | Dispatcher switching on `ctx.type` to render DiffContext/EmailContext/MeetingContext/ChatContext. Props: `ctx`. |

#### Settings Sub-tab Primitive

| Component | File | Purpose |
|---|---|---|
| `Tabs` | `components/ui/tabs.tsx` | Radix UI Tabs wrapper following shadcn/ui pattern. Exports: `Tabs` (root), `TabsList` (horizontal flex container with bottom border), `TabsTrigger` (individual tab button with 2px solid --primary bottom border on active, text-muted-foreground inactive, text-foreground active), `TabsContent` (panel wrapper). |

### Changed Components

#### AppSidebar.tsx

**Changes:**
1. Add hover-expand behavior: rail widens from 64px to 216px on hover with 0.18s ease transition. Labels appear with opacity transition (0 -> 1, 0.14s ease). Box-shadow on hover. `:focus-within` also triggers expansion for keyboard users.
2. Add logo button at top: WB icon (34x34) + "WorkBench" label (display font, weight 600). Navigates to `/` on click. Margin-bottom 12px.
3. Update NAV array to 7 items: Overview (LayoutDashboard), Search (Search), Triage (ListChecks), Action Items (CircleCheckBig), Ingestion (Workflow), Knowledge (BookOpen), Settings (Settings). Remove Sources (Database) and Messenger (MessageSquare).
4. Each NavLink renders icon + label text (label hidden at 64px via opacity:0, visible on hover).
5. Active item: 2px orange left bar (existing) + label visible in expanded state.
6. CSS class `wb-rail-nav` on outer nav element.
7. Respect `prefers-reduced-motion`: disable width/opacity transitions.

#### AppShell.tsx

**Changes:**
1. Render `<Breadcrumb />` component inside main content area, above `{children}`.

#### TopBar.tsx

**Changes:**
1. Add `/search` -> `'SEARCH'` mapping to `ROUTE_LABELS`.
2. Add `/filters` -> `'INGESTION.FUNNEL'` mapping.
3. Add `/settings/sources` -> `'SETTINGS.SOURCES'` and `/settings/messenger` -> `'SETTINGS.MESSENGER'` mappings.

#### Overview.tsx

**Changes:**
1. Hot Feed items become clickable buttons. Clicking opens ItemFunnelDialog for the item.
2. Add SourceFlow Sankey in Infrastructure section (replace or augment Topology).
3. Stalled source indicators: sources with `health_status === 'erroring'` show red dashed ribbons, TriangleAlert icon, "STALLED" label in SourceFlow.
4. Add state `[overviewItem, setOverviewItem]` for dialog. Render ItemFunnelDialog conditionally.

#### Triage.tsx

**Changes:**
1. Add explanatory subtitle under page title: "Priorities are estimated by the model from relevance and urgency signals -- not user-set."
2. Priority badges show "est" prefix. Tooltip: "Estimated priority -- model-scored from relevance + urgency signals, not user-set." Estimated priority badge implementation: existing priority Badge component receives an `estimated?: boolean` prop. When true, renders "est {priority}" text and shows the tooltip on hover. No separate component needed.
3. Add "Focus by theme" section at top of left filter rail. Clickable theme cards with type counts (diff/task/meeting/note), label, summary. Clicking activates theme filter. State: `themeFilter` (string|null).
4. Replace Signal Velocity card with Throughput multi-line chart: 3 series (Ingestion #ff6a2b, Triage queue #9a7af0, Triaged #71d2ff) over 24h.
5. Card summary becomes clickable button calling `onOpenItem` callback. Opens ItemFunnelDialog.
6. Add state `[triageItem, setTriageItem]` for ItemFunnelDialog.

#### ActionItems.tsx

**Changes:**
1. **Remove** WorkModeCard component, `useWorkMode` import, `workMode` state, and all Work Mode conditional rendering.
2. **Remove** the two-column stat grid (ThroughputCard + WorkModeCard).
3. **Add** full-width throughput chart Card using MultiLineChart. Two series: "Incoming actions" (#ff6a2b) and "Completion rate" (#9ad08a). Header: "Throughput (12h)" + inline counts (in/done/net with color coding). Initially uses mock 12-hour arrays; future endpoint `GET /api/stats/throughput-timeseries`.
4. **Add** conditional Filter Tuning section above throughput chart. Renders when `fb.openTasks().length > 0`. Uses FilterTuningCard for each task. Section header: "Filter Tuning ({count})".
5. **Add** `useFeedbackStore()` hook integration.

#### Ingestion.tsx

**Changes:**
1. **Replace** "Live Ingestion Log" section (LogStream + activityLogLine) with LiveTail component.
2. **Add** live/paused toggle button in SectionHeader right slot.
3. **Add** `tailItem` and `tailLive` state for ItemFunnelDialog and pause control.
4. **Move** LiveTail section higher in layout (after stat cards, before warnings).
5. **Add** queue stats as top-level stat cards.
6. **Embed** `<IngestionFunnel />` (FiltersPage) at bottom.
7. **Promote** dead letters to dedicated Warnings section.

#### Settings.tsx

**Changes:**
1. **Refactor** to container with sub-tabs using hybrid Radix + React Router pattern (see Decision: Settings Tab Routing). Page header h1 "Settings", Tabs navigation with three TabsTrigger (System with SlidersHorizontal icon, Sources with Database icon, Messenger with MessageSquare icon), content area rendering active tab.
2. **Extract** current Settings content into `SettingsSystem` component (becomes System tab content).
3. **Use** React Router sub-routes: `/settings` (index -> System), `/settings/sources`, `/settings/messenger`.
4. Active tab derived from `pathname.split('/')[2]` with fallback to `'system'`. Radix `Tabs` receives `value={activeTab}` as a controlled component. Each `TabsTrigger` has `onClick={() => navigate('/settings/{tab}')}` in addition to the Radix `value` prop.
5. Clicking a tab navigates via `navigate()`.

#### Sources.tsx

**Changes:**
1. Accept optional `embedded?: boolean` prop.
2. When `embedded=true`, hide page-level h1 title (Settings container provides the title and tab navigation).

#### Messenger.tsx

**Changes:**
1. Accept optional `embedded?: boolean` prop.
2. When `embedded=true`, hide page-level h1 title.

---

## Pages

### New Pages

#### FiltersPage (`/filters`)

**File:** `pages/Filters.tsx`
**Export:** `IngestionFunnel` (also used as embedded component in Ingestion page)

**Layout (top to bottom):**
1. Header bar: "evaluation order" label + "Add filter" button
2. Interleaved funnel cards: enrichers, filters, loopbacks in a single reorderable list
3. Funnel Output table: recent items with treatment summary and final verdict
4. Dialogs: AddRuleDialog, FilterDetailDialog, EnricherDetailDialog, ItemFunnelDialog

**State:**
- `rawRules` -- filter rules from API
- `enrichers` -- enricher configs from API
- `loopbacks` -- loop-back stages from API
- `order` -- unified sequence of `{ kind: 'enricher'|'filter'|'loopback', id }`
- Dialog states for AddRule, FilterDetail, EnricherDetail, ItemFunnel

**Interactions:**
- Reorder any stage up/down (single unified ordering). **Reorder debounce:** optimistic UI update fires immediately on arrow click; debounced `PATCH /api/funnel/order` fires after 500ms of idle (no further reorder clicks). On server error, roll back to previous order with toast: "Reorder failed -- reverted."
- Toggle enable/disable via Switch
- Delete filter rules
- Create new filter rules via AddRuleDialog
- Click filter card -> FilterDetailDialog
- Click enricher card -> EnricherDetailDialog
- Click any item in Funnel Output -> ItemFunnelDialog
- Correction picker in FunnelStage -> feedback store

**Data:** `useFilterRules()`, `useEnrichers()`, `useLoopbacks()`, `useFunnelItems()`, `useFeedbackStore()`

**Five-state UI:** See Five-State UI Taxonomy section above.

#### SearchPage (`/search`)

**File:** `pages/Search.tsx`

**Layout:**
1. Title + description
2. Search input (auto-focused) with icon, clear button, result count (`{count} results` in mono, hidden when no query)
3. Kind filter buttons (All / Diffs / Email / Meetings / Chat)
4. Master/detail split: 340px result list (left, sticky) | detail pane (right)

**State:**
- `q` -- search query string
- `kind` -- kind filter (all/diff/email/meeting/chat)
- `selId` -- selected item ID
- `toast` -- transient notification (2.2s auto-dismiss via sonner)

**Filtering:** Client-side via `useMemo`. Text search: case-insensitive `.includes()` across summary, id, source, tags, llm_summary. Kind filter: `=== check` on item.kind. No API call until `query.length >= 2`. Server-side `/api/items/search` returns max 100 items per request. Pagination is a future enhancement if the corpus grows beyond this limit.

**Keyboard navigation (required for WCAG compliance):**
- Arrow Up/Down: navigate result list items
- Enter: select highlighted result (opens detail pane)
- Escape: clear selection, return focus to search input
- Result list uses `role="listbox"`, each `ResultRow` uses `role="option"`, container tracks `aria-activedescendant`

**Interactions:**
- Type to search
- Click kind filter buttons
- Click ResultRow to select
- Item actions: set priority (select), mark done, snooze 4h, archive, delete -- all via mutations with toast feedback
- Keyboard navigation as described above

**Data:** `useSearchItems(q, kind)`, `useUpdateItem()`, `useSnoozeItem()`, `useArchiveItem()`

**Five-state UI:**
1. Loading: skeleton grid (left) + detail skeleton (right)
2. Error: alert with message + request ID + "Retry" button
3. Unauthorized: full-page lockout (reuse from Overview)
4. Empty (filtered): "No items match filters" in dashed border card
5. Empty (no query): "Type to search" centered in left panel; right panel shows dashed border with "select an item to inspect its full processing log"

#### SettingsSystem

**File:** `pages/SettingsSystem.tsx`

Content extracted from current Settings.tsx: app version, config version, component health badges, redacted config sections via JsonHighlight, locked secrets vault, download backup button. No new data requirements.

### Changed Pages

All changes are described in the Components section above. The routing changes are:

**App.tsx additions:**
```
/search          -> <Search />
/filters         -> <Filters />
/settings        -> <Settings />  (container with Outlet)
  /settings      -> <SettingsSystem /> (index route)
  /settings/sources   -> <Sources embedded />
  /settings/messenger -> <Messenger embedded />
```

**Preserved routes (backward compat):**
```
/sources    -> <Sources />       (standalone, embedded=false)
/messenger  -> <Messenger />     (standalone, embedded=false)
```

---

## Data Flow

### New API Endpoints (Server-Side)

#### Feedback Correction Loop

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| `GET` | `/api/feedback/overrides` | List all filter corrections | -- | `FeedbackOverride[]` |
| `POST` | `/api/feedback/overrides` | Record a new correction (creates override + tuning task) | `{itemId, itemSummary, filterId, filterPrompt, fromOutcome, toOutcome, toLabel?}` | `{override, task}` |
| `DELETE` | `/api/feedback/overrides/{itemId}/{filterId}` | Remove a correction and dismiss associated open task | -- | `{status: 'deleted'}` |
| `GET` | `/api/feedback/tasks` | List filter-tuning tasks | `?status=open\|applied\|dismissed` | `FilterTuningTask[]` |
| `POST` | `/api/feedback/tasks/{taskId}/apply` | Apply a prompt patch (writes to filter store) | -- | `{status: 'applied'}` |
| `POST` | `/api/feedback/tasks/{taskId}/dismiss` | Dismiss a tuning task | -- | `{status: 'dismissed'}` |

#### Funnel Data

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| `GET` | `/api/items/{itemId}/funnel` | Full funnel trace for an item | -- | `{item, stages[], verdict, loop_count}` |
| `GET` | `/api/filter-rules/{filterId}/items` | Items processed by a specific filter | `?limit=` | `{items[], total}` |
| `GET` | `/api/enrichers` | List all enricher configs with stats | -- | `Enricher[]` |
| `GET` | `/api/enrichers/{enricherId}/samples` | Enrichment samples for an enricher | `?limit=3` | `EnrichmentSample[]` |
| `GET` | `/api/loopbacks` | List loop-back control stages | -- | `LoopBack[]` |
| `GET` | `/api/funnel/items` | Recent items with full funnel traces | `?limit=100` | `FunnelItem[]` |
| `GET` | `/api/funnel/order` | Unified stage ordering | -- | `[{kind, id, order}]` |
| `PATCH` | `/api/funnel/order` | Update stage ordering | `{items: [{kind, id, order}]}` | `{status: 'updated'}` |
| `PATCH` | `/api/funnel/stages/{id}` | Toggle stage enabled/disabled | `{enabled: bool}` | `{status: 'updated'}` |

#### Filter Rule Extensions

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| `PATCH` | `/api/filter-rules/{filterId}` | Update filter rule (enable/disable, prompt) | `{enabled?, prompt?}` | `FilterRule` |
| `DELETE` | `/api/filter-rules/{filterId}` | Delete a filter rule | -- | `{status: 'deleted'}` |
| `PATCH` | `/api/filter-rules/{filterId}/prompt` | Update filter prompt (manual edits or auto-tuning) | `{prompt}` | `{status: 'updated'}` |

#### Search (Enhanced)

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| `GET` | `/api/items/search` | Full-text search with rich item data (max 100 results) | `?q=&kind=&limit=` (limit capped at 100) | `SearchItem[]` (with llm_summary, enriched_context, processing_log, verdict, tags) |
| `POST` | `/api/items/{itemId}/snooze` | Snooze an item | `{hours}` | `{status: 'snoozed'}` |

**Removed from previous revision:** ~~`GET /api/flow-matrix`~~ -- SourceFlow flow matrix is client-computed (see Decision: SourceFlow Flow Matrix).

**Existing endpoints to extend:**
- `PATCH /api/items/{item_id}` -- already accepts `ItemUpdate` (priority, status, summary). No schema change needed.
- `DELETE /api/items/{item_id}` -- already exists for archive. No change needed.
- `GET /api/filter-rules` -- already exists but needs to return extended fields (prompt, action, sources, confidence, origin, matched, enabled, label, order_index).

### New TanStack Query Hooks

#### hooks/useFeedback.ts

| Hook | Endpoint | Polling | Purpose |
|---|---|---|---|
| `useFeedbackOverrides()` | `GET /api/feedback/overrides` | 30s | List all corrections |
| `useAddOverride()` | `POST /api/feedback/overrides` | mutation | Record a correction |
| `useRemoveOverride()` | `DELETE /api/feedback/overrides/{itemId}/{filterId}` | mutation | Remove a correction + dismiss open task |
| `useFeedbackTasks(status?)` | `GET /api/feedback/tasks?status=` | 15s | List tuning tasks |
| `useApplyTask()` | `POST /api/feedback/tasks/{taskId}/apply` | mutation | Apply prompt patch |
| `useDismissTask()` | `POST /api/feedback/tasks/{taskId}/dismiss` | mutation | Dismiss task |

#### hooks/useFunnel.ts

| Hook | Endpoint | Polling | Purpose |
|---|---|---|---|
| `useFilterRules()` | `GET /api/filter-rules` | 30s | Extended filter rules |
| `useEnrichers()` | `GET /api/enrichers` | 60s | Enricher configs |
| `useLoopbacks()` | `GET /api/loopbacks` | 60s | Loop-back stages |
| `useFunnelItems(limit?)` | `GET /api/funnel/items?limit=` | 15s | Items with funnel traces (live tail) |
| `useItemFunnel(itemId)` | `GET /api/items/{itemId}/funnel` | no poll (dialog-only) | Single item trace |
| `useFilterItems(filterId)` | `GET /api/filter-rules/{filterId}/items` | no poll (dialog-only) | Items for a filter |
| `useEnricherSamples(enricherId)` | `GET /api/enrichers/{enricherId}/samples` | no poll | Enrichment samples |
| `useToggleFilterRule()` | `PATCH /api/filter-rules/{filterId}` | mutation | Toggle enable/disable |
| `useDeleteFilterRule()` | `DELETE /api/filter-rules/{filterId}` | mutation | Delete filter |
| `useReorderFunnel()` | `PATCH /api/funnel/order` | mutation | Reorder stages (debounced 500ms) |
| `useUpdateFilterPrompt()` | `PATCH /api/filter-rules/{filterId}/prompt` | mutation | Update prompt |

#### hooks/useSearchItems.ts

| Hook | Endpoint | Polling | Purpose |
|---|---|---|---|
| `useSearchItems(q, kind, limit)` | `GET /api/items/search?q=&kind=&limit=` | 15s when query non-empty | Full search results (max 100) |
| `useItemActions()` | Various PATCH/POST/DELETE | mutations | Priority/done/snooze/archive/delete |
| `useSnoozeItem()` | `POST /api/items/{itemId}/snooze` | mutation | Snooze item |

#### Custom Hook (non-TanStack)

| Hook | Source | Purpose |
|---|---|---|
| `useFeedbackStore()` | `lib/feedback-store.ts` | React hook subscribing to WBFeedback singleton. Forces re-render on any state change. Returns the WBFeedback API object. Subscribes on mount, unsubscribes on unmount. |

### New TypeScript Types

#### lib/types/funnel.ts

```typescript
// Filter rule actions
type FilterAction = 'drop' | 'include' | 'label' | 'context'

// Stage outcome including pass-through values
type StageOutcome = FilterAction | 'pass' | 'skip' | 'loopback'

// Origin of a filter rule
type FilterOrigin = 'learned' | 'explicit'

// Extended filter rule (beyond current FilterRule domain model)
interface FilterRuleExtended {
  id: string
  prompt: string
  action: FilterAction
  sources: string[]
  confidence: number
  origin: FilterOrigin
  matched: number
  enabled: boolean
  label?: string
  order_index: number
  created_at: string
  updated_at: string
}

// Enricher configuration
interface Enricher {
  id: string
  type: string
  label: string
  enabled: boolean
  depth: 'shallow' | 'deep'
  adds: string[]        // field names added
  records: string[]     // entity types recorded
  budget: { max_calls: number; max_time_ms: number }
  enriched: number      // count
  avg_calls: number
  avg_ms: number
}

// Loop-back control stage
interface LoopBack {
  id: string
  label: string
  enabled: boolean
  kind: 'loopback'
  trigger: string
  condition: string
  max_loops: number
  looped: number        // count
  avg_loops: number
}

// Single funnel stage record
interface FunnelStage {
  filterId: string
  outcome: StageOutcome
  confidence?: number
  reason: string
  context?: string
  label?: string
  weak?: boolean
  timestamp?: string
  duration?: number
}

// Item with full funnel trace
interface FunnelItem {
  id: string
  summary: string
  source: string
  created_at: string
  stages: FunnelStage[]
  verdict: Verdict
  loop_count: number    // tracked per-item, incremented on loop-back re-injection
}

// Final verdict on an item
interface Verdict {
  decision: 'queued' | 'dropped' | 'triaged'
  priority?: string     // null/undefined = omit priority badge from VerdictPill
  confidence: number
  rationale: string
}

// Enrichment sample for detail dialog
interface EnrichmentSample {
  itemId: string
  summary: string
  contextKV: Record<string, string>
  entities: Array<{ type: string; name: string }>
}

// Unified funnel ordering entry
interface FunnelOrderEntry {
  kind: 'enricher' | 'filter' | 'loopback'
  id: string
  order: number
}
```

#### lib/types/feedback.ts

```typescript
interface FeedbackOverride {
  id: string
  itemId: string
  itemSummary: string
  filterId: string
  filterPrompt: string
  fromOutcome: string
  fromLabel?: string
  toOutcome: string
  toLabel?: string
  at: string // ISO timestamp
}

// FilterTuningTask extends FeedbackOverride with tuning-specific fields.
// The `proposedPrompt` field is populated by the `refinedPrompt()` function
// (see lib/feedback-store.ts). The function name describes the action
// (refining the prompt), while the field name describes the stored result
// (the proposed new prompt text).
interface FilterTuningTask extends FeedbackOverride {
  kind: 'filter-tuning'
  status: 'open' | 'applied' | 'dismissed'
  proposedPrompt: string
}
```

#### lib/types/search.ts

```typescript
type ItemKind = 'diff' | 'email' | 'meeting' | 'chat'

type ItemState = 'triaged' | 'pending_triage' | 'action_item' | 'dropped' | 'archived'

interface DiffContext {
  type: 'diff'
  author: string
  team: string
  status: string
  url: string
  hunks: Array<{ file: string; header: string; rank: number; code: string }>
}

interface EmailContext {
  type: 'email'
  from: string
  to: string
  when: string
  body: string
}

interface MeetingContext {
  type: 'meeting'
  when: string
  duration: string
  location: string
  attendees: string[]
  agenda: string | null
}

interface ChatContext {
  type: 'chat'
  channel: string
  messages: Array<{ author: string; text: string; ts: string }>
}

type ItemContext = DiffContext | EmailContext | MeetingContext | ChatContext

interface SearchItem {
  id: string
  kind: ItemKind
  state: ItemState
  priority: string
  relevance: number
  summary: string
  source: string
  created_at: string
  tags: string[]
  llm_summary: string
  context: ItemContext
  log: FunnelStage[]
  verdict: Verdict
}
```

#### lib/types/triage.ts (additions)

```typescript
interface TriageTheme {
  id: string
  label: string
  summary: string
  cards: string[]  // card IDs
  counts: Record<string, number>  // by type: diff/task/meeting/note
}
```

### New Lib Modules

#### lib/funnel-constants.ts

```typescript
// ACTION_META: action -> {label, icon, chipFg, chipBg, accent}
// Action labels (used by ActionChip):
//   drop: 'Drop'
//   include: 'Include'
//   label: 'Label: {label}'  (label param interpolated at render time)
//   context: 'Add context'
//   pass: 'Pass'
//   skip: 'Skip'
//   loopback: 'Loop back'
//
// STAGE_META: extends ACTION_META with pass and skip
// SRC_ICON: source -> lucide icon name mapping
// Color values from design prototype
```

#### lib/feedback-store.ts

**WBFeedback** -- module-scoped singleton (pattern matches existing `api.ts` token cache).

**State:** `{overrides[], tasks[], promptPatches: Map<filterId, string>}`

**Persistence:** `localStorage` with key `'workbench.feedback'`, serialize/deserialize on load/change. Cross-tab sync via `storage` event listener. **Fallback behavior:** if `localStorage.setItem()` throws (e.g., quota exceeded, private browsing), the store operates in-memory only. A warning toast is shown on the **first** correction attempt that fails to persist: "Corrections are stored in memory only -- they will not survive page reload." No toast on subsequent corrections. Cross-tab sync is disabled in fallback mode. The store sets an internal `_persisted: boolean` flag on initialization.

**API:**
- `subscribe(fn) -> unsubscribe` -- pub/sub for React re-renders
- `overrideFor(itemId, filterId)` -- lookup single override
- `feedbackForFilter(filterId)` -- all overrides for a filter
- `openTasks()` -- tasks with `status=open`
- `promptFor(filterId, fallback)` -- patched prompt or fallback
- `addOverride({...})` -- record override + create tuning task with `refinedPrompt()`
- `removeOverride(itemId, filterId)` -- remove override + dismiss its open task (see Decision: Filter Correction Undo Semantics)
- `autoApply(taskId)` -- apply proposed prompt to `promptPatches`
- `dismissTask(taskId)` -- mark task as dismissed

**`refinedPrompt()`:** Appends `"-- but [verb] cases like [itemSummary] (you corrected this)."` to the original prompt. Models closed-loop learning. The return value is stored in the task's `proposedPrompt` field.

**FeedbackOverride to FilterTuningTask relationship:** 1:1 mapping. A `FilterTuningTask` is created immediately when an override is added via `addOverride()`. The task's `proposedPrompt` is generated by `refinedPrompt()` at creation time. Dismissing a task (via `dismissTask()`) does NOT delete the associated override -- the correction remains in effect for display purposes (strikethrough in FunnelStage). Deleting an override (via `removeOverride()`) DOES dismiss the associated open task.

**Server integration:** Overrides/tasks read from `/api/feedback/*` on mount to seed initial state. Mutations write to server for persistence. `promptPatches` are local-only until auto-applied (POST writes to server).

**Exposed globally:** `window.WBFeedback` for debugging (follows existing `window.WB` pattern).

#### lib/funnel-helpers.ts

```typescript
// ruleById(id) -- find rule or enricher by ID
// enricherStageFor(item) -- synthesize enrichment step for treatment log
// itemLog(item) -- full treatment log, enricher leads
// stageDuration(stage) -- deterministic per-stage timing from hash
// stageTimings(log) -- cumulative {at, dur} timeline
// buildFlowMatrix(sources, stats, queue) -- compute SourceFlow flow matrix
//   from SourceRollup[], StatsOverview, and QueueStats. Maps each source's
//   items_stored count proportionally into the by_status breakdown (triaged,
//   dropped, pending_triage, action_item). Returns Record<sourceId, Record<outputBucket, number>>.
```

### New Storage Repositories (Server-Side)

Five new repository interfaces in `storage/base.py` with PostgreSQL implementations in `storage/postgres/`:

| Store | Purpose |
|---|---|
| `FeedbackStore` | `add_correction()`, `get_corrections_for_filter()`, `delete_correction()`, `add_tuning_task()`, `get_open_tasks()`, `apply_task()`, `dismiss_task()` |
| `EnrichersStore` | `get_enrichers()`, `update_enricher(id, enabled)` |
| `LoopBacksStore` | `get_loopbacks()`, `update_loopback(id, enabled)` |
| `FunnelTracesStore` | `get_recent_items_with_traces(limit)`, `get_item_trace(item_id)` |
| `FunnelOrderStore` | `get_order()`, `update_order(items)` |

Existing `FilterRuleStore` needs extension:
- `update_rule(id, updates)` -- enable/disable, prompt update
- `delete_rule(id)`
- `reorder_rules(order)`

Existing `Stores` class needs new store fields added to `__init__`.

### Database Migrations

**Migration 009: Feedback system + funnel extensions**

New tables:
1. `feedback_corrections` -- id, item_id, filter_id, from_outcome, from_label, to_outcome, to_label, created_at
2. `feedback_tasks` -- id, kind, status, item_id, item_summary, filter_id, filter_prompt, from_outcome, to_outcome, proposed_prompt, created_at, updated_at
3. `enricher_configs` -- id, type, label, enabled, depth, adds (JSONB), records (JSONB), budget (JSONB), enriched_count, avg_calls, avg_ms, created_at
4. `loopback_configs` -- id, label, enabled, trigger, condition, max_loops, looped_count, avg_loops, created_at
5. `funnel_stages` -- id, kind (enricher/filter/loopback), stage_id, order_index, enabled, created_at

Schema changes to `filter_rules` table:
- ADD `prompt TEXT` (replaces `pattern` conceptually -- migrate existing `pattern` values)
- ADD `sources JSONB DEFAULT '[]'`
- ADD `confidence INTEGER DEFAULT 0`
- ADD `origin VARCHAR DEFAULT 'explicit'`
- ADD `matched INTEGER DEFAULT 0`
- ADD `enabled BOOLEAN DEFAULT TRUE`
- ADD `label VARCHAR`
- ADD `order_index INTEGER`
- ADD `updated_at TIMESTAMPTZ`

**Data migration for pattern -> prompt rename:**

```sql
-- Forward migration: copy pattern values into new prompt column
UPDATE filter_rules SET prompt = pattern WHERE prompt IS NULL AND pattern IS NOT NULL;

-- The pattern column is NOT dropped -- kept as nullable for backward compatibility
-- during the transition period. New code writes to prompt; reads prefer prompt
-- with fallback to pattern.
```

**Rollback strategy for pattern -> prompt:**

```sql
-- Reverse migration: copy prompt back to pattern if it was migrated
UPDATE filter_rules SET pattern = prompt WHERE pattern IS NULL AND prompt IS NOT NULL;

-- Then drop the new columns
ALTER TABLE filter_rules DROP COLUMN IF EXISTS prompt;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS sources;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS confidence;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS origin;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS matched;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS enabled;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS label;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS order_index;
ALTER TABLE filter_rules DROP COLUMN IF EXISTS updated_at;
```

Schema changes to `items` table:
- ADD `tags JSONB DEFAULT '[]'`
- ADD `llm_summary TEXT`
- ADD `enriched_context JSONB`
- ADD `funnel_log JSONB` (array of stage records; includes top-level `loop_count` key)
- ADD `verdict_decision VARCHAR`
- ADD `verdict_priority VARCHAR`
- ADD `verdict_confidence INTEGER`
- ADD `verdict_rationale TEXT`

Indexes:
- `items(summary)` -- GIN trigram index for fast ILIKE (`CREATE INDEX idx_items_summary_trgm ON items USING gin (summary gin_trgm_ops);` -- requires `pg_trgm` extension)
- `items(created_at DESC)` -- for funnel items query
- `feedback_corrections(item_id, filter_id)` -- unique constraint
- `feedback_tasks(status)` -- for open tasks query
- `funnel_stages(order_index)` -- for ordered retrieval

**Extension dependency:** The GIN trigram index requires `CREATE EXTENSION IF NOT EXISTS pg_trgm;` at the start of the migration.

### Domain Model Changes (Server-Side)

**domain/filters.py** -- extend `FilterRule`:
```python
class FilterRule(BaseModel):
    id: str
    prompt: str            # was: pattern
    action: str            # expand to: drop/include/label/context
    sources: list[str] = []
    confidence: int = 0
    origin: str = 'explicit'  # learned | explicit
    matched: int = 0
    enabled: bool = True
    label: str | None = None
    order_index: int = 0
    source_type: str | None = None  # kept for backward compat
    pattern: str | None = None      # deprecated, mapped from prompt
    priority: Priority | None = None
    created_from_interaction_id: str | None = None
```

**New domain models:**
- `domain/feedback.py` -- `FeedbackCorrection`, `FilterTuningTask`
- `domain/enrichment.py` -- extend with `EnricherConfig`, add `LoopBackConfig`
- `domain/items.py` -- extend `Item` with `tags`, `llm_summary`, `enriched_context`, `funnel_log`, `verdict_decision`, `verdict_priority`, `verdict_confidence`, `verdict_rationale`

---

## Cross-cutting Patterns

### Feedback Correction Loop

The complete closed-loop flow:

1. **Observe:** User sees an item's funnel trace (on Filters, Search, Ingestion, or Overview page via ItemFunnelDialog)
2. **Correct:** User clicks "correct" on a FunnelStage where the filter misclassified
3. **Choose:** Correction picker appears: "This should have been..." with outcome choices (Keep/include, Drop, Label spam, No action)
4. **Record:** On selection: override recorded in feedback store (client + server), tuning task created with `refinedPrompt()` (return value stored as task's `proposedPrompt` field). FeedbackOverride and FilterTuningTask have a 1:1 relationship.
5. **Surface:** On Filters page: FilterDetailDialog shows correction summary; FunnelStage shows corrected outcome with strikethrough of original. On Actions page: FilterTuningCard appears in "Filter Tuning" section.
6. **Apply:** User can "Auto-apply update" (writes refined prompt to filter store) or dismiss ("I'll do it manually")
7. **Propagate:** Auto-applied prompts flow back: filter cards show "tuned" indicator, detail dialogs show "prompt auto-tuned from your feedback"
8. **Undo:** User can undo a correction via the FunnelStage "undo" button (see Decision: Filter Correction Undo Semantics)

### Per-Item Funnel Trace

Every item carries a `stages[]` array recording what each enricher and filter did. The `itemLog()` function guarantees the enricher step leads. `stageTimings()` computes deterministic timing. This trace is viewable from five surfaces:
- Filters page Funnel Output table
- Search page detail pane (processing log section)
- Ingestion page LiveTail (click row -> ItemFunnelDialog)
- Overview page Hot Feed (click item -> ItemFunnelDialog)
- Triage page (click card summary -> ItemFunnelDialog)

### ItemFunnelDialog Conditional Mounting Pattern

Each page that uses ItemFunnelDialog manages its own state and conditionally mounts the component:

```tsx
const [dialogItem, setDialogItem] = useState<FunnelItem | null>(null)

// ... in JSX:
{dialogItem && <ItemFunnelDialog item={dialogItem} onClose={() => setDialogItem(null)} />}
```

The `item` prop on `ItemFunnelDialog` is typed as `FunnelItem` (non-nullable). The component is only mounted when `dialogItem` is non-null, so the prop is always satisfied. This avoids internal null-checking inside the dialog component.

### Enricher-Filter Interleaving

The funnel is NOT "all enrichers then all filters." Enrichers and filters are interleaved per source type in the unified ordering: enrich github items -> run github-relevant filters -> enrich email items -> run email-relevant filters. The ordering is unified and reorderable through the Filters page.

### Loop-Back Control Stage

A stage that re-injects items at the top of the funnel when source material changes (new diff revision, new email reply, agenda edit). Has a max-loop guard to prevent infinite cycling. Per-item loop count is tracked in the `funnel_log` JSONB (see Decision: Per-Item Loop Count Tracking). Represented as a card in the funnel ordering alongside enrichers and filters.

### Estimated Priority

All model-scored priorities display with "est" prefix and tooltip explanation. This distinguishes model-estimated priorities from user-set priorities across Triage and Search pages. The distinction is purely presentational -- the data model uses the same Priority enum. When priority is null (not yet scored), the priority badge is omitted entirely from the display.

### Portal Pattern

Dialogs that need to escape parent overflow/z-index stacking render through the Portal component (`ReactDOM.createPortal` to `document.body`). Used by ItemFunnelDialog, FilterDetailDialog, EnricherDetailDialog, AddRuleDialog.

### ItemFunnelDialog Reuse

Single component instance shared across Overview, Triage, Ingestion, Search, and Filters pages. Each page manages its own `[dialogItem, setDialogItem]` state and conditionally mounts the dialog (see ItemFunnelDialog Conditional Mounting Pattern above).

### CSS Additions (index.css)

```css
/* Live tail flash animation */
.wb-tail-new { animation: wb-tail-flash 1.1s ease; }
@keyframes wb-tail-flash {
  0%   { background: color-mix(in srgb, var(--primary) 12%, transparent); }
  100% { background: transparent; }
}

/* Hover-expand rail */
.wb-rail-nav {
  position: absolute;
  width: 64px;
  transition: width 0.18s ease, box-shadow 0.18s ease;
  overflow: hidden;
}
.wb-rail-nav:hover, .wb-rail-nav:focus-within {
  width: 216px;
  box-shadow: var(--shadow-pop);
}
.wb-rail-label {
  opacity: 0;
  transition: opacity 0.14s ease;
}
.wb-rail-nav:hover .wb-rail-label,
.wb-rail-nav:focus-within .wb-rail-label {
  opacity: 1;
}
.wb-rail-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  background: var(--primary);
}

@media (prefers-reduced-motion: reduce) {
  .wb-rail-nav, .wb-rail-label, .wb-tail-new { transition: none; animation: none; }
}
```

---

## Testing Strategy

### Five-Layer Approach

#### Layer 1: Unit Tests for Helpers

| Module | Tests |
|---|---|
| `lib/feedback-store.ts` | `addOverride` creates task + calls `refinedPrompt()`, `removeOverride` clears override + dismisses open task, `removeOverride` on applied task shows no task dismissal (already applied), `autoApply` updates promptPatches, `promptFor` returns patched prompt with fallback, `subscribe`/notify works, localStorage persistence round-trips, cross-tab sync via storage event, localStorage fallback (in-memory only when setItem throws, warning toast on first correction only) |
| `lib/funnel-helpers.ts` | `ruleById()`, `itemLog()` (enricher always leads), `stageTimings()` cumulative computation, `stageDuration()` deterministic hashing, `enricherStageFor()`, `buildFlowMatrix()` proportional calculation correctness |
| `lib/funnel-constants.ts` | `ACTION_META` and `STAGE_META` have correct keys, all seven action label strings match spec, `SRC_ICON` maps all known sources |

#### Layer 2: Component Tests

| Component | Key Assertions |
|---|---|
| `Portal` | Renders children into document.body; removes portal on unmount |
| `ActionChip` | Renders each action type with correct icon/label/colors; 'label' action shows "Label: {label}"; confidence percentage when provided; all seven label strings verified |
| `ConfidenceBar` | Correct color thresholds (green >= 90, primary >= 80); aria-valuenow |
| `VerdictPill` | Color-coded by decision; shows priority + confidence when priority present; omits priority badge when priority is null; large variant |
| `StateDot` | Correct colors per state; label text |
| `SourceChip` | Icon + name for each source type; default icon for unknown |
| `Breadcrumb` | Hidden at "/"; shows "Back to Overview" from /triage; shows "Back to Triage" from /triage/123; shows "Back to Settings" from /settings/sources; shows "Back to Overview" from /filters |
| `FunnelStage` | Renders stage details; enricher stages use tertiary border, filter stages use brand color, loopback stages use primary color; correction picker opens on "correct" click; correction submission calls addOverride; strikethrough on corrected outcome; "undo" removes override (with confirmation dialog when task already applied); timing display when timing props present; timing row omitted when timing props null; editable vs read-only mode |
| `FilterTuningCard` | Renders task data; onApply callback; onDismiss callback; proposed prompt visible |
| `FilterRuleCard` | Order number; action chip; prompt; source chips; reorder buttons work; toggle fires onToggle; "tuned" indicator when feedback patched |
| `EnricherCard` | Source icon; depth badge; field/entity chips; budget display; toggle; tertiary left border |
| `LoopBackCard` | Label; max loops badge; condition text; toggle; primary left border |
| `MultiLineChart` | Renders with series data; hover shows tooltip; tooltip flips when x > containerWidth * 0.75; tooltip flips when right edge would exceed container minus 40px padding; legend row |
| `LiveTail` | Renders 5 column headers; no new rows when paused; click row fires onOpenItem; newest row has wb-tail-new class; max 60 rows; five UI states (loading skeleton, error alert, empty message, paused indicator, degraded stale-data warning) |
| `ResultRow` | Kind icon; priority badge; StateDot; active state styling |
| `Tabs` (ui) | Radix wrapper passes props; applies className; renders children |

#### Layer 3: Integration Tests (Dialog Workflows)

| Dialog | Tests |
|---|---|
| `ItemFunnelDialog` | Renders all stages; shows corrected outcomes with strikethrough; timing calculations correct; timing omitted for null timing props; verdict section with rationale; escape to close; focus trap; loop_count displayed |
| `FilterDetailDialog` | Renders items for filter; correction summary box; row click fires onOpenItem |
| `EnricherDetailDialog` | Renders samples; context k/v chips; entity list |
| `AddRuleDialog` | Form validation; submit fires onCreate; LLM not regex messaging |

#### Layer 4: Page Tests

| Page | Tests |
|---|---|
| `Filters.test.tsx` | Renders funnel cards in order; reorder changes sequence; reorder debounce (500ms); optimistic update + rollback on error; toggle enable/disable; add filter dialog flow; funnel output table renders items; item click opens dialog; five UI states (loading/error/empty/unauthorized/degraded) |
| `Search.test.tsx` | Empty state on load; search input auto-focuses; kind filtering works; clicking result selects and shows detail; item actions trigger mutations with toast; contextual renderers display correctly; five UI states; keyboard navigation (arrow up/down, Enter, Escape); role=listbox/option ARIA attributes; max 100 results |
| `ActionItems.test.tsx` (updated) | Work Mode removal verified; throughput chart renders; filter tuning section conditional on open tasks; existing bucket tests preserved |
| `Triage.test.tsx` (updated) | Priority badge "est" prefix; tooltip accessible; theme filtering; card summary clickable; throughput chart |
| `Settings.test.tsx` (updated) | Tab navigation via URL; Radix value derived from pathname; route-driven active state; all three panels render; embedded prop tests for Sources/Messenger; arrow key navigation between tabs; proper ARIA attributes (role=tablist, role=tab, aria-selected) |
| `Ingestion.test.tsx` (updated) | LiveTail renders; pause toggle works; dead letter promotion; funnel embedded |

#### Layer 5: API Tests (Server-Side)

New endpoints with test database: verify schema, pagination, error handling, correct HTTP status codes. Use existing test patterns (pytest + httpx + test database).

| Endpoint Group | Tests |
|---|---|
| `/api/feedback/*` | CRUD for overrides; task lifecycle (create -> apply/dismiss); DELETE override also dismisses open task; concurrent correction race |
| `/api/funnel/*` | Order retrieval and update; stage toggle; items with traces; reorder idempotency |
| `/api/items/search` | Full-text search; kind filtering; limit capped at 100; rich response shape |
| `/api/enrichers` | List with stats; samples endpoint |

### MSW Mock Handlers (Client Tests)

Add handlers to `test/server.ts` for all new endpoints:
- `/api/feedback/overrides` (GET, POST, DELETE)
- `/api/feedback/tasks` (GET, POST)
- `/api/filter-rules/:id/items` (GET)
- `/api/items/:id/funnel` (GET)
- `/api/enrichers` (GET)
- `/api/enrichers/:id/samples` (GET)
- `/api/loopbacks` (GET)
- `/api/funnel/items` (GET)
- `/api/items/search` (GET)
- `/api/items/:id/snooze` (POST)

### Accessibility Tests

Update `a11y.test.tsx` to verify:
- Settings route has proper tab ARIA attributes (role=tablist, role=tab, aria-selected)
- Search page: result list has role=listbox with role=option items, aria-activedescendant tracking, keyboard navigation (arrow/enter/escape)
- LiveTail: aria-live=polite, role=table structure
- SourceFlow: role=img with comprehensive aria-label, visually-hidden table fallback
- FunnelStage correction picker: keyboard navigation
- All new dialogs: aria-modal, aria-labelledby, focus trap, Escape-to-close
- ActionChip/VerdictPill/StateDot: color + text/icon redundancy (not color-only)
- ConfidenceBar: aria-valuenow/valuemin/valuemax
- Hover-expand rail: labels accessible even when visually hidden; :focus-within expansion

---

## Migration Notes

### Breaking Changes

1. **Work Mode removal:** `useWorkMode` hook and `WORK_MODE_KEY` localStorage key become dead code. The `useWorkMode.ts` file and `useWorkMode.test.ts` can be deleted. Action Items page no longer imports them.

2. **FilterRule domain model:** The `pattern` field is renamed to `prompt` conceptually. Migration 009 includes explicit data migration SQL (`UPDATE filter_rules SET prompt = pattern WHERE prompt IS NULL AND pattern IS NOT NULL;`). The `pattern` column is kept as nullable for backward compatibility during the transition. Rollback strategy is documented in the Database Migrations section.

3. **Navigation restructure:** Sources and Messenger are removed from the sidebar rail. Users who have bookmarked `/#/sources` or `/#/messenger` will still reach the standalone pages (routes preserved). But the primary path is now Settings > [Sources|Messenger] tab.

### Implementation Branch Order

The work is split into branches to keep each focused:

**Branch 1: Core Infrastructure** (prerequisite for all others)
- Portal component (with explicit `children: ReactNode` prop)
- SectionHeader component
- ActionChip + funnel-constants.ts (with all seven action label strings)
- ConfidenceBar, VerdictPill (with null-priority handling), StateDot, SourceChip
- Breadcrumb component (with full route mapping table)
- Tabs (ui) primitive
- funnel-helpers.ts (including `buildFlowMatrix()`)
- feedback-store.ts + useFeedbackStore hook (with localStorage fallback behavior)
- CSS additions to index.css (wb-tail-new animation, wb-rail-nav)
- New TypeScript types (funnel, feedback, search)

**Branch 2: Shell + Settings** (depends on Branch 1)
- AppSidebar hover-expand + nav restructure
- AppShell breadcrumb integration
- TopBar route label additions
- Settings sub-tabs (hybrid Radix + React Router pattern) + SettingsSystem extraction
- Sources/Messenger embedded prop
- App.tsx route additions for /settings/*

**Branch 3: Feedback System + Action Items** (depends on Branch 1)
- FilterTuningCard component
- FunnelStage component (core of feedback loop, with enricher/filter/loopback visual differentiation and timing fallback)
- ItemFunnelDialog component (with conditional mounting pattern documented)
- Action Items page modifications (remove Work Mode, add MultiLineChart, add filter tuning section)
- Server: feedback endpoints, migration 009 (feedback tables + pattern->prompt data migration with rollback SQL)
- Server: /api/items/{id}/funnel endpoint
- Hooks: useFeedback.ts
- Tests: feedback store (including undo semantics and localStorage fallback), FilterTuningCard, FunnelStage, ItemFunnelDialog

**Branch 4: Ingestion + Live Tail** (depends on Branch 3)
- LiveTail component (with five UI states documented)
- Ingestion page modifications
- Server: /api/funnel/items endpoint
- Hooks: useFunnelItems
- Tests: LiveTail (all five states), Ingestion page updates

**Branch 5: Filters Page (Ingestion Funnel)** (depends on Branch 3)
- FiltersPage (with five UI states) with FilterRuleCard, EnricherCard, LoopBackCard
- FilterDetailDialog, EnricherDetailDialog, AddRuleDialog
- Funnel ordering API + storage (with 500ms debounce + optimistic UI + rollback)
- Server: enrichers, loopbacks, funnel order endpoints
- Server: migration 009 additions (enricher_configs, loopback_configs, funnel_stages tables, pg_trgm extension, GIN trigram index)
- Hooks: useFunnel.ts (all funnel hooks)
- Tests: Filters page (including reorder debounce), detail dialogs

**Branch 6: Search Page** (depends on Branch 3)
- SearchPage + all sub-components (ResultRow, SearchItemDetail, contextual renderers)
- Required keyboard navigation (arrow/enter/escape, role=listbox/option)
- Server: /api/items/search endpoint (max 100 results), /api/items/{id}/snooze endpoint
- Server: migration 009 additions (items table columns)
- Hooks: useSearchItems.ts
- App.tsx /search route
- Tests: Search page (including keyboard nav, five UI states, ARIA compliance)

**Branch 7: Overview + Triage Enhancements** (depends on Branch 3)
- Overview: clickable Hot Feed, SourceFlow integration (client-computed flow matrix)
- Triage: estimated priority (with null-priority omission), focus-by-theme, card click-through, throughput chart
- SourceFlow component (with five UI states, animation parameters, hover re-proportioning algorithm)
- Tests: Overview, Triage updates, SourceFlow (layout, focus, stalled, animation pause on hidden tab)

**Branch 8: SourceFlow** (can be independent or part of Branch 7)
- SourceFlow Sankey component
- Animation system (rAF loop, 80-dot pool, 2.8s duration, spawn rate proportional to flow, recycling at output nodes, visibility API pause)
- Stalled source detection
- Hover isolation + re-proportioning (300ms ease CSS transition)
- Click navigation
- Accessibility (role=img, sr-only table, prefers-reduced-motion)
- Tests: layout computation, focus state, stalled rendering

### Performance Budget

| Concern | Mitigation |
|---|---|
| FunnelItems query (all items with stages) | Paginate, limit to 100 items, index on created_at |
| EnrichmentSamples per enricher | Lazy-load on dialog open, limit to 3 samples |
| Search corpus with context payloads | Server-side search with limit (max 100), debounce input 200ms |
| ItemFunnelDialog 10+ stages | React.memo on FunnelStage, useMemo for stageTimings |
| SourceFlow rAF animation | 80-dot pool cap, pause when tab hidden (visibilityChange), prefers-reduced-motion |
| LiveTail streaming | 60-row cap via slice(-60), clearInterval on unmount/pause, rAF for scroll |
| Filter reordering | Optimistic UI + debounced PATCH (500ms idle window), CSS transitions, rollback on error with toast |
| useFeedbackStore subscriptions | Unsubscribe on unmount, shallow equality to avoid unnecessary re-renders |
| MultiLineChart smoothPath | Memoize path strings, debounce mousemove tooltip |
| Result list rendering | React.memo on ResultRow, virtualize if > 100 items |

### File Inventory Summary

**Total: 40 new files, 12 modified files, 1 deleted file (client-side) + 10 new server files, 10 modified server files.**

**New client files (40):**
- `components/Portal.tsx`
- `components/SectionHeader.tsx`
- `components/ActionChip.tsx`
- `components/ConfidenceBar.tsx`
- `components/VerdictPill.tsx`
- `components/StateDot.tsx`
- `components/SourceChip.tsx`
- `components/Breadcrumb.tsx`
- `components/MultiLineChart.tsx`
- `components/SourceFlow.tsx`
- `components/FilterTuningCard.tsx`
- `components/LiveTail.tsx`
- `components/ui/tabs.tsx`
- `components/funnel/FunnelStage.tsx`
- `components/funnel/ItemFunnelDialog.tsx`
- `components/funnel/FilterRuleCard.tsx`
- `components/funnel/FilterDetailDialog.tsx`
- `components/funnel/EnricherCard.tsx`
- `components/funnel/EnricherDetailDialog.tsx`
- `components/funnel/LoopBackCard.tsx`
- `components/funnel/AddRuleDialog.tsx`
- `components/search/ResultRow.tsx`
- `components/search/SearchItemDetail.tsx`
- `components/search/contextual/DiffContext.tsx`
- `components/search/contextual/EmailContext.tsx`
- `components/search/contextual/MeetingContext.tsx`
- `components/search/contextual/ChatContext.tsx`
- `components/search/contextual/ItemContext.tsx`
- `pages/Filters.tsx`
- `pages/Search.tsx`
- `pages/SettingsSystem.tsx`
- `hooks/useFeedback.ts`
- `hooks/useFunnel.ts`
- `hooks/useSearchItems.ts`
- `lib/funnel-constants.ts`
- `lib/feedback-store.ts`
- `lib/funnel-helpers.ts`
- `lib/types/funnel.ts`
- `lib/types/feedback.ts`
- `lib/types/search.ts`

**Modified client files (12):**
- `App.tsx` -- route additions
- `components/AppSidebar.tsx` -- hover-expand, nav restructure, logo
- `components/AppShell.tsx` -- breadcrumb
- `components/TopBar.tsx` -- route labels
- `pages/Overview.tsx` -- clickable Hot Feed, SourceFlow, ItemFunnelDialog
- `pages/Triage.tsx` -- est priority, themes, card click, throughput chart
- `pages/ActionItems.tsx` -- remove Work Mode, add MultiLineChart, add filter tuning
- `pages/Ingestion.tsx` -- LiveTail, queue stats, dead letters, embedded funnel
- `pages/Settings.tsx` -- sub-tab container (hybrid Radix + React Router)
- `pages/Sources.tsx` -- embedded prop
- `pages/Messenger.tsx` -- embedded prop
- `index.css` -- wb-tail-new, wb-rail-nav, wb-rail-label CSS

**Deleted client files (1):**
- `hooks/useWorkMode.ts` (+ `hooks/useWorkMode.test.ts`) -- dead code after Work Mode removal

**New server files (10):**
- `src/workbench/api/feedback.py`
- `src/workbench/api/enrichers.py`
- `src/workbench/api/loopbacks.py`
- `src/workbench/api/funnel.py`
- `src/workbench/domain/feedback.py`
- `src/workbench/storage/postgres/feedback.py`
- `src/workbench/storage/postgres/enrichers.py`
- `src/workbench/storage/postgres/loopbacks.py`
- `src/workbench/storage/postgres/funnel.py`
- `src/workbench/migrations/versions/009_dashboard_v3.py`

**Modified server files (10):**
- `src/workbench/domain/filters.py` -- FilterRule extended
- `src/workbench/domain/items.py` -- Item extended with new fields
- `src/workbench/domain/enrichment.py` -- EnricherConfig, LoopBackConfig added
- `src/workbench/storage/base.py` -- new store interfaces, Stores class extended
- `src/workbench/storage/postgres/filter_rules.py` -- extended operations
- `src/workbench/storage/postgres/items.py` -- new columns
- `src/workbench/storage/postgres/stores.py` -- new store wiring
- `src/workbench/api/filter_rules.py` -- PATCH, DELETE endpoints
- `src/workbench/api/items.py` -- snooze endpoint
- `src/workbench/runtime/app.py` -- register new routers