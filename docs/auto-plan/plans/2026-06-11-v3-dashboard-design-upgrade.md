Now I have all the context. Let me produce the complete updated plan with all issues fixed.

# WorkBench v3 Dashboard Design Upgrade -- Implementation Plan

## Slice 1: Foundation Types + Constants + Helpers

**Title:** New TypeScript types, funnel constants, and helper modules

**Description:** Create the foundational type definitions, constants, and pure utility functions that every subsequent slice imports. No components, no API calls, no visual changes. This is pure data-layer groundwork. TriageTheme is added to the existing `useTriage.ts` hook file (which already contains TriageCard, TriageOption, etc.) rather than creating a separate triage types file.

**Files to create:**
- `ui/src/lib/types/funnel.ts` -- FilterAction, StageOutcome, FilterOrigin, FilterRuleExtended, Enricher, LoopBack, FunnelStage, FunnelItem, Verdict, EnrichmentSample, FunnelOrderEntry
- `ui/src/lib/types/feedback.ts` -- FeedbackOverride, FilterTuningTask
- `ui/src/lib/types/search.ts` -- ItemKind, ItemState, DiffContext, EmailContext, MeetingContext, ChatContext, ItemContext, SearchItem
- `ui/src/lib/funnel-constants.ts` -- ACTION_META, STAGE_META, SRC_ICON maps with colors/icons/labels for all seven action types
- `ui/src/lib/funnel-helpers.ts` -- ruleById, enricherStageFor, itemLog (enricher always leads), stageDuration (deterministic hash), stageTimings (cumulative), buildFlowMatrix (proportional source-to-output mapping: takes per-source ingest counts and per-output-bucket counts, computes proportional ribbon weights by distributing each source's volume across output buckets in proportion to global output ratios)

**Files to modify:**
- `ui/src/hooks/useTriage.ts` -- Add `TriageTheme` interface (theme label + color + item count) alongside existing TriageCard/TriageOption types

**Files to delete:** None

**Tests:**
- `ui/src/lib/funnel-constants.test.ts` -- ACTION_META/STAGE_META keys match spec, all seven label strings, SRC_ICON covers all known sources
- `ui/src/lib/funnel-helpers.test.ts` -- ruleById, itemLog enricher-leads ordering, stageTimings cumulative math, stageDuration deterministic, buildFlowMatrix proportional correctness (verifies ribbon weights sum to source total, output columns sum to bucket totals, single-source/single-output edge case, all-zero input returns empty matrix)

**Complexity:** S

**Dependencies:** None

**Parallelizable with:** Slice 2 (server foundation)

---

## Slice 2: Server Foundation -- Domain Models, Migration, Storage

**Title:** Server-side domain models, Alembic migration 009, new repository interfaces and PG implementations

**Description:** Extend the server's domain layer with feedback, enricher config, loopback config, and item extensions. Create migration 009 with the following transaction order: (1) CREATE EXTENSION IF NOT EXISTS pg_trgm, (2) new tables (feedback_corrections, filter_tuning_tasks, enrichers, loopbacks, funnel_stages, funnel_order), (3) ADD COLUMN prompt (text, nullable) to filter_rules -- this is an addition alongside the existing pattern column which is kept nullable for backward compatibility during transition, not a replacement, (4) ADD COLUMN for sources/confidence/origin/matched/enabled/label/order_index on filter_rules, (5) ADD COLUMN for tags/llm_summary/enriched_context/funnel_log/verdict_* on items, (6) CREATE GIN index using pg_trgm on items for full-text search. The pattern-to-prompt data migration: copies pattern into prompt WHERE prompt IS NULL AND pattern IS NOT NULL; rows where both are NULL are left untouched (they will need prompt values set through the UI or API before becoming active). Add five new storage interfaces (FeedbackStore, EnrichersStore, LoopBacksStore, FunnelTracesStore, FunnelOrderStore) with PostgreSQL implementations. Extend FilterRuleStore and Stores class. New store parameters are added as keyword-only arguments (after the existing `close_fn` parameter with `*` separator) to avoid breaking existing positional callers: `feedback: FeedbackStore`, `enrichers: EnrichersStore`, `loopbacks: LoopBacksStore`, `funnel_traces: FunnelTracesStore`, `funnel_order: FunnelOrderStore`.

**Rollback SQL note:** The rollback for prompt column uses `UPDATE filter_rules SET pattern = prompt WHERE pattern IS NULL AND prompt IS NOT NULL` (matching the forward migration's WHERE clause) to avoid overwriting any existing pattern values that were preserved during the forward migration.

**Files to create:**
- `src/workbench/domain/feedback.py` -- FeedbackCorrection, FilterTuningTask pydantic models
- `src/workbench/storage/postgres/feedback.py` -- PgFeedbackStore implementation
- `src/workbench/storage/postgres/enrichers.py` -- PgEnrichersStore implementation
- `src/workbench/storage/postgres/loopbacks.py` -- PgLoopBacksStore implementation
- `src/workbench/storage/postgres/funnel.py` -- PgFunnelTracesStore, PgFunnelOrderStore implementations
- `src/workbench/migrations/versions/009_dashboard_v3.py` -- All new tables, columns, indexes, pg_trgm extension (extension created BEFORE GIN index in transaction order)

**Files to modify:**
- `src/workbench/domain/filters.py` -- Extend FilterRule with prompt (nullable text, added alongside existing nullable pattern), sources, confidence, origin, matched, enabled, label, order_index fields
- `src/workbench/domain/items.py` -- Add tags, llm_summary, enriched_context, funnel_log, verdict_* fields to Item
- `src/workbench/domain/enrichment.py` -- Add EnricherConfig, LoopBackConfig models
- `src/workbench/storage/base.py` -- Add FeedbackStore, EnrichersStore, LoopBacksStore, FunnelTracesStore, FunnelOrderStore ABCs; extend FilterRuleStore with update_rule, delete_rule, reorder_rules; extend Stores.__init__ with five new keyword-only store params after `*` separator (feedback, enrichers, loopbacks, funnel_traces, funnel_order)
- `src/workbench/storage/postgres/filter_rules.py` -- Implement update_rule, delete_rule, reorder_rules
- `src/workbench/storage/postgres/items.py` -- Handle new columns in queries
- `src/workbench/storage/postgres/stores.py` -- Wire new PG stores into create_postgres_stores, pass as keyword arguments

**Files to delete:** None

**Tests:**
- `tests/storage/test_feedback_store.py` -- CRUD for corrections, task lifecycle
- `tests/storage/test_funnel_store.py` -- Order retrieval/update, trace queries
- `tests/test_migration_009.py` -- Forward/rollback smoke test, verify pg_trgm extension exists before GIN index creation, verify pattern-to-prompt migration handles NULL+NULL rows (leaves them untouched), verify rollback WHERE clause preserves existing pattern values

**Complexity:** L

**Dependencies:** None

**Parallelizable with:** Slice 1 (client foundation)

---

## Slice 3: Server API Endpoints

**Title:** New FastAPI routers for feedback, funnel, enrichers, loopbacks, and enhanced search/items

**Description:** Create four new API router modules (feedback, funnel, enrichers, loopbacks). Extend filter_rules router with PATCH/DELETE. Extend items router with snooze endpoint. Create new search endpoint `/api/items/search` returning rich SearchItem results with llm_summary, enriched_context, processing_log, verdict, tags. Search results are capped at `min(requested_limit, 100)` -- the endpoint accepts an optional `limit` query parameter and always caps it to 100 maximum regardless of what the client requests. Register all new routers in runtime/app.py.

**Files to create:**
- `src/workbench/api/feedback.py` -- GET/POST/DELETE overrides, GET/POST tasks
- `src/workbench/api/enrichers.py` -- GET enrichers, GET enricher samples
- `src/workbench/api/loopbacks.py` -- GET loopbacks
- `src/workbench/api/funnel.py` -- GET/PATCH funnel order, PATCH stage toggle, GET funnel items, GET item funnel trace

**Files to modify:**
- `src/workbench/api/filter_rules.py` -- Add PATCH (update), DELETE, PATCH prompt endpoints
- `src/workbench/api/items.py` -- Add POST snooze endpoint, add GET /api/items/search with `limit = min(request.limit or 50, 100)` cap logic
- `src/workbench/runtime/app.py` -- Import and register feedback, enrichers, loopbacks, funnel routers

**Files to delete:** None

**Tests:**
- `tests/api/test_feedback_api.py` -- CRUD overrides, task lifecycle, DELETE cascade
- `tests/api/test_funnel_api.py` -- Order, toggle, items, item trace
- `tests/api/test_enrichers_api.py` -- List, samples
- `tests/api/test_items_search.py` -- Full-text search, kind filter, limit cap (requesting 200 returns at most 100), rich response shape

**Complexity:** L

**Dependencies:** Slice 2

**Parallelizable with:** Slice 4 (client shared components, if Slice 1 done)

---

## Slice 4: Shared UI Primitives

**Title:** Portal, SectionHeader, ActionChip, ConfidenceBar, VerdictPill, StateDot, SourceChip, Breadcrumb, Tabs

**Description:** Build all shared visual primitives used by multiple pages. Each is a pure presentational component with no API calls. Portal wraps ReactDOM.createPortal. SectionHeader is a mono uppercase label. ActionChip/VerdictPill/StateDot/SourceChip render color-coded status indicators. ConfidenceBar renders a progress bar with ARIA. Breadcrumb reads React Router location for back navigation. Tabs wraps Radix UI primitives in shadcn/ui pattern. Note: the `Search` icon from lucide-react is confirmed available in the installed version (exported from `lucide-react/dist/esm/icons/search.js`) and will be imported in Slice 7 for AppSidebar changes.

**Files to create:**
- `ui/src/components/Portal.tsx`
- `ui/src/components/SectionHeader.tsx`
- `ui/src/components/ActionChip.tsx`
- `ui/src/components/ConfidenceBar.tsx`
- `ui/src/components/VerdictPill.tsx`
- `ui/src/components/StateDot.tsx`
- `ui/src/components/SourceChip.tsx`
- `ui/src/components/Breadcrumb.tsx`
- `ui/src/components/ui/tabs.tsx`

**Files to modify:** None

**Files to delete:** None

**Tests:**
- `ui/src/components/Portal.test.tsx` -- Renders into document.body, cleanup on unmount
- `ui/src/components/ActionChip.test.tsx` -- All seven action labels, confidence display, colors
- `ui/src/components/ConfidenceBar.test.tsx` -- Color thresholds, aria-valuenow
- `ui/src/components/VerdictPill.test.tsx` -- Decision colors, null priority omits badge, large variant
- `ui/src/components/StateDot.test.tsx` -- Colors per state
- `ui/src/components/SourceChip.test.tsx` -- Icon per source, fallback
- `ui/src/components/Breadcrumb.test.tsx` -- Hidden at /, correct labels per route
- `ui/src/components/ui/tabs.test.tsx` -- Wrapper props, className passthrough

**Complexity:** M

**Dependencies:** Slice 1

**Parallelizable with:** Slice 3 (server APIs)

---

## Slice 5: Feedback Store + useFeedbackStore Hook

**Title:** Client-side feedback correction store with localStorage persistence, server sync, and React hook

**Description:** Create the WBFeedback module-scoped singleton with pub/sub, localStorage persistence (with in-memory fallback), cross-tab sync, and server API integration. Create useFeedbackStore hook that subscribes to the singleton and forces re-renders. Expose as window.WBFeedback for debugging. Implements `refinedPrompt()` as a private function within `feedback-store.ts` that computes a proposed prompt string from override data -- this is distinct from the `proposedPrompt` field on FilterTuningTask which stores the persisted result of calling refinedPrompt(). Override/task 1:1 relationship with proper undo semantics.

**Files to create:**
- `ui/src/lib/feedback-store.ts` -- WBFeedback singleton, all API methods, private `refinedPrompt()` function for prompt auto-tuning computation
- `ui/src/hooks/useFeedback.ts` -- TanStack Query hooks for /api/feedback/* endpoints + useFeedbackStore custom hook

**Files to modify:** None

**Files to delete:** None

**Tests:**
- `ui/src/lib/feedback-store.test.ts` -- addOverride creates task via refinedPrompt (verify refinedPrompt is called internally and produces proposedPrompt field), removeOverride clears + dismisses, autoApply updates promptPatches, promptFor fallback, subscribe/notify, localStorage roundtrip, cross-tab sync via storage event, localStorage fallback (in-memory when setItem throws)
- `ui/src/hooks/useFeedback.test.ts` -- TanStack query integration, mutation callbacks

**Complexity:** M

**Dependencies:** Slice 1 (types), Slice 3 (server endpoints for sync)

**Parallelizable with:** Slice 4 (shared components)

---

## Slice 6: Funnel Core Components -- FunnelStage + ItemFunnelDialog

**Title:** FunnelStage timeline component and ItemFunnelDialog modal

**Description:** Build FunnelStage (vertical timeline with colored circle, connecting line, outcome display, correction picker, undo, timing, enricher/filter/loopback visual differentiation). The `timing` prop accepts `TimingInfo | null | undefined` -- both null and undefined trigger the same fallback behavior (displays "-- ms" placeholder). Build ItemFunnelDialog (full item provenance modal with header, treatment log, aggregated verdict). These are the core reusable components for the feedback correction loop visible on 5 pages. Also create MultiLineChart (custom SVG, Catmull-Rom curves, tooltip flip logic, legend).

**Canonical ItemFunnelDialog mounting pattern:** All pages that open ItemFunnelDialog follow a single pattern: (1) page holds `const [funnelItemId, setFunnelItemId] = useState<string | null>(null)`, (2) clickable element calls `setFunnelItemId(item.id)`, (3) `<ItemFunnelDialog itemId={funnelItemId} open={!!funnelItemId} onClose={() => setFunnelItemId(null)} />` renders at page root. All subsequent slice descriptions reference this canonical pattern rather than re-describing it.

**Files to create:**
- `ui/src/components/funnel/FunnelStage.tsx` -- timing prop typed as `timing?: TimingInfo | null` (both null and undefined trigger "-- ms" fallback)
- `ui/src/components/funnel/ItemFunnelDialog.tsx`
- `ui/src/components/MultiLineChart.tsx`
- `ui/src/components/FilterTuningCard.tsx`

**Files to modify:** None

**Files to delete:** None

**Tests:**
- `ui/src/components/funnel/FunnelStage.test.tsx` -- Stage details, enricher/filter/loopback borders, correction picker, undo, timing display when TimingInfo provided, timing null shows "-- ms" fallback, timing undefined shows "-- ms" fallback, editable vs read-only
- `ui/src/components/funnel/ItemFunnelDialog.test.tsx` -- All stages rendered, corrected outcomes strikethrough, timing, verdict section, escape-to-close, loop_count
- `ui/src/components/MultiLineChart.test.tsx` -- Series rendering, tooltip flip at 75% x-threshold, tooltip flip when right edge exceeds container width minus 40px, legend
- `ui/src/components/FilterTuningCard.test.tsx` -- Task data, onApply/onDismiss callbacks

**Complexity:** L

**Dependencies:** Slice 1 (types/helpers), Slice 4 (ActionChip, VerdictPill, ConfidenceBar, Portal), Slice 5 (useFeedbackStore)

**Parallelizable with:** Slice 7 (after deps met)

---

## Slice 7: Shell Changes -- Nav, Breadcrumbs, Hover-Expand, CSS

**Title:** AppSidebar hover-expand, AppShell breadcrumb, TopBar route labels, CSS additions

**Description:** Restructure the nav rail: add hover-expand (64px -> 216px), logo button, update NAV array from 8 items to 7 items by: removing Sources (currently position 5, path /sources) and Messenger (currently position 7, path /messenger), and adding Search (icon: `Search` from lucide-react, path /search) at position 2 (between Overview and Triage). Final NAV order: Overview, Search, Triage, Action Items, Ingestion, Knowledge, Settings. Add labels with opacity transition. Add Breadcrumb to AppShell. Add new route labels to TopBar. CSS approach: the existing AppSidebar uses NavLink with inline className function (isActive -> border-l-2 border-primary). The hover-expand behavior adds a `wb-rail-nav` class to the `<nav>` element for the width transition. Individual nav item hover/active styles continue to use NavLink's className callback; the `wb-rail-item` CSS class is NOT needed since NavLink handles active state. The `wb-rail-label` class targets the new text labels for opacity transition.

**Files to create:** None

**Files to modify:**
- `ui/src/components/AppSidebar.tsx` -- Add `Search` to lucide-react imports, hover-expand behavior via wb-rail-nav class on nav element, logo button, NAV restructure (remove Sources at position 5 + Messenger at position 7, add Search at position 2 = 7 items total), label text spans with wb-rail-label class, prefers-reduced-motion, :focus-within expansion
- `ui/src/components/AppShell.tsx` -- Import and render Breadcrumb above children
- `ui/src/components/TopBar.tsx` -- Add /search, /filters, /settings/* route label mappings
- `ui/src/index.css` -- wb-tail-new animation, wb-rail-nav width transition (64px->216px), wb-rail-label opacity transition, prefers-reduced-motion media query (no wb-rail-item class -- active state handled by NavLink inline)

**Files to delete:** None

**Tests:**
- `ui/src/components/AppSidebar.test.tsx` -- 7 nav items, Search present at position 2, Sources absent, Messenger absent, labels with wb-rail-label class, wb-rail-nav class on nav element
- `ui/src/components/AppShell.test.tsx` -- Breadcrumb rendered
- Update `ui/src/a11y.test.tsx` -- Hover-expand rail labels accessible, :focus-within

**Complexity:** M

**Dependencies:** Slice 4 (Breadcrumb component)

**Parallelizable with:** Slice 6 (funnel components)

---

## Slice 8: Settings Sub-tabs

**Title:** Settings page refactor to sub-tab container with hybrid Radix + React Router routing

**Description:** Refactor Settings.tsx into a container with three Radix Tabs (System/Sources/Messenger) driven by React Router URL state. Extract current Settings content into SettingsSystem.tsx. Add embedded prop to Sources.tsx and Messenger.tsx. Add React Router sub-routes in App.tsx. Active tab state derived from pathname. Standalone /sources and /messenger routes preserved for backward compat. Settings.tsx must import `Outlet` from react-router-dom to render nested route content within the Radix tab panels.

**Files to create:**
- `ui/src/pages/SettingsSystem.tsx` -- Extracted from current Settings.tsx

**Files to modify:**
- `ui/src/pages/Settings.tsx` -- Refactor to tab container with Radix Tabs + React Router; import `Outlet` from react-router-dom and render `<Outlet />` inside the active tab panel for nested route content
- `ui/src/pages/Sources.tsx` -- Accept embedded?: boolean prop, conditionally hide h1
- `ui/src/pages/Messenger.tsx` -- Accept embedded?: boolean prop, conditionally hide h1
- `ui/src/App.tsx` -- Add /search, /filters routes; add /settings/* nested routes with SettingsSystem index, Sources and Messenger as child routes

**Files to delete:** None

**Tests:**
- `ui/src/pages/Settings.test.tsx` -- Tab navigation via URL, Radix value from pathname, all three panels render, Outlet renders child route content, ARIA attributes (tablist/tab/aria-selected)
- `ui/src/pages/Sources.test.tsx` -- embedded prop hides h1
- `ui/src/pages/Messenger.test.tsx` -- embedded prop hides h1
- Update `ui/src/a11y.test.tsx` -- Settings tabs ARIA compliance

**Complexity:** M

**Dependencies:** Slice 4 (Tabs component), Slice 7 (route changes in App.tsx)

**Parallelizable with:** Slice 9 (after Slice 7 merges)

---

## Slice 9: Action Items Changes

**Title:** Remove Work Mode, add MultiLineChart throughput, add Filter Tuning section

**Description:** Remove WorkModeCard, useWorkMode import, work mode conditional rendering, and the two-column stat grid. Add full-width MultiLineChart throughput card with two series (incoming/completion). Add conditional Filter Tuning section using FilterTuningCard when feedback store has open tasks. Delete useWorkMode.ts and useWorkMode.test.ts. Note: WORK_MODE_KEY is only referenced within useWorkMode.ts itself and ActionItems.tsx (via the `useWorkMode` hook import) -- no other files import WORK_MODE_KEY directly, so deleting useWorkMode.ts and removing the import from ActionItems.tsx is sufficient.

**Files to create:** None

**Files to modify:**
- `ui/src/pages/ActionItems.tsx` -- Remove `import { useWorkMode } from '@/hooks/useWorkMode'`, remove WorkModeCard component and its rendering (both in work-mode branch and in the two-column grid), remove two-column grid layout, add full-width throughput MultiLineChart, add filter tuning section with useFeedbackStore

**Files to delete:**
- `ui/src/hooks/useWorkMode.ts`
- `ui/src/hooks/useWorkMode.test.ts`

**Tests:**
- `ui/src/pages/ActionItems.test.tsx` -- Work Mode absent, throughput chart renders, filter tuning conditional on open tasks, existing bucket tests preserved

**Complexity:** M

**Dependencies:** Slice 5 (useFeedbackStore), Slice 6 (MultiLineChart, FilterTuningCard)

**Parallelizable with:** Slice 10

---

## Slice 10: Triage Page Changes

**Title:** Estimated priority badges, focus-by-theme filter, card click-through, throughput chart

**Description:** Add explanatory subtitle about estimated priorities. Priority badges show "est" prefix with tooltip. The Badge component (`ui/src/components/ui/badge.tsx`) is extended with an `estimated?: boolean` prop: when true, the badge text is prefixed with "est" and wrapped in a tooltip explaining the estimate. Add "Focus by theme" section to left filter rail with clickable theme cards. Replace Signal Velocity card with throughput MultiLineChart (3 series). Card summary becomes clickable, opening ItemFunnelDialog (see canonical mounting pattern in Slice 6).

**Files to create:**
- `ui/src/hooks/useFunnel.ts` -- TanStack Query hooks for funnel endpoints (useFilterRules, useEnrichers, useLoopbacks, useFunnelItems, useItemFunnel, etc.)

**Files to modify:**
- `ui/src/components/ui/badge.tsx` -- Add `estimated?: boolean` prop to BadgeProps; when true, prefix content with "est" text and wrap in Tooltip
- `ui/src/pages/Triage.tsx` -- Est priority badges (pass estimated prop to Badge), theme filter, card summary click, throughput chart, ItemFunnelDialog state (canonical pattern)

**Files to delete:** None

**Tests:**
- `ui/src/components/ui/badge.test.tsx` -- estimated prop shows "est" prefix, tooltip present when estimated, no prefix when estimated is false/undefined
- `ui/src/pages/Triage.test.tsx` -- Priority badge "est" prefix, tooltip, theme filtering, card summary clickable, throughput chart renders

**Complexity:** M

**Dependencies:** Slice 6 (ItemFunnelDialog, MultiLineChart), Slice 4 (shared components)

**Parallelizable with:** Slice 9

---

## Slice 11: Ingestion Page Changes + LiveTail

**Title:** LiveTail component, queue stats promotion, dead letter promotion, embedded funnel

**Description:** Build LiveTail component (auto-scrolling 5-column table, 226px fixed height, 60-row cap, wb-tail-new flash, live/paused toggle, five UI states). Replace LogStream section with LiveTail. Promote queue stats to top-level stat cards. Promote dead letters to Warnings section. Embed the Filters page component (imported as `IngestionFunnel` -- this is a named re-export of the Filters component, see Slice 12) at the bottom of the Ingestion page.

**Files to create:**
- `ui/src/components/LiveTail.tsx` -- Streaming table with pause, click-to-open, five UI states

**Files to modify:**
- `ui/src/pages/Ingestion.tsx` -- Replace LogStream with LiveTail, promote queue stats, promote dead letters, import IngestionFunnel from Filters page and embed at bottom

**Files to delete:** None

**Tests:**
- `ui/src/components/LiveTail.test.tsx` -- 5 column headers, pause stops rows, click fires onOpenItem, wb-tail-new class, max 60 rows, all five UI states
- `ui/src/pages/Ingestion.test.tsx` -- LiveTail present, LogStream absent, queue stats promoted, funnel embedded

**Complexity:** M

**Dependencies:** Slice 6 (ItemFunnelDialog), Slice 10 (useFunnel hooks), Slice 7 (CSS for wb-tail-new)

**Parallelizable with:** Slice 12

---

## Slice 12: Ingestion Funnel Page (Filters)

**Title:** FiltersPage with interleaved funnel cards, reordering, detail dialogs

**Description:** Build the /filters page. The file is `ui/src/pages/Filters.tsx` with the primary component named `Filters`. It is exported both as the default export and as a named re-export `IngestionFunnel` for embedding in the Ingestion page: `export { Filters as IngestionFunnel }`. Interleaved enricher/filter/loopback cards in a single reorderable list. FilterRuleCard, EnricherCard, LoopBackCard with toggle/delete/reorder. AddRuleDialog for new filter creation (includes a disclaimer that matching uses the LLM with natural language patterns, not regex). FilterDetailDialog showing items processed by a filter. EnricherDetailDialog showing enrichment samples. Funnel Output table at bottom. Reorder with 500ms debounce, optimistic UI, rollback on error. Five UI states.

**Files to create:**
- `ui/src/pages/Filters.tsx` -- Main page component exported as both `Filters` (default) and `IngestionFunnel` (named re-export: `export { Filters as IngestionFunnel }`)
- `ui/src/components/funnel/FilterRuleCard.tsx`
- `ui/src/components/funnel/FilterDetailDialog.tsx`
- `ui/src/components/funnel/EnricherCard.tsx`
- `ui/src/components/funnel/EnricherDetailDialog.tsx`
- `ui/src/components/funnel/LoopBackCard.tsx`
- `ui/src/components/funnel/AddRuleDialog.tsx`
- `ui/src/hooks/useSearchItems.ts` -- useSearchItems, useItemActions, useSnoozeItem hooks

**Files to modify:** None (App.tsx route already added in Slice 8)

**Files to delete:** None

**Tests:**
- `ui/src/pages/Filters.test.tsx` -- Funnel cards in order, reorder changes sequence, reorder debounce, optimistic + rollback, toggle, add filter, funnel output, item click opens dialog, five UI states
- `ui/src/components/funnel/FilterRuleCard.test.tsx` -- Order number, action chip, toggle, tuned indicator
- `ui/src/components/funnel/EnricherCard.test.tsx` -- Tertiary border, depth badge, toggle
- `ui/src/components/funnel/LoopBackCard.test.tsx` -- Max loops badge, primary border
- `ui/src/components/funnel/AddRuleDialog.test.tsx` -- Form validation, submit, LLM disclaimer text present ("matches with the LLM, not regex")
- `ui/src/components/funnel/FilterDetailDialog.test.tsx` -- Items for filter, correction summary, row click
- `ui/src/components/funnel/EnricherDetailDialog.test.tsx` -- Samples, context chips

**Complexity:** L

**Dependencies:** Slice 4 (primitives), Slice 5 (feedback store), Slice 6 (FunnelStage, ItemFunnelDialog), Slice 10 (useFunnel hooks)

**Parallelizable with:** Slice 13

---

## Slice 13: Search Page

**Title:** Full corpus search with master/detail, contextual renderers, keyboard navigation

**Description:** Build /search page with search input, kind filter buttons, master/detail split. ResultRow and SearchItemDetail components. Four contextual renderers (DiffContext, EmailContext, MeetingContext, ChatContext) dispatched by ItemContext. Processing log using FunnelStage components. Required keyboard navigation (arrow/enter/escape) with WCAG listbox/option ARIA. Five UI states.

**Files to create:**
- `ui/src/pages/Search.tsx`
- `ui/src/components/search/ResultRow.tsx`
- `ui/src/components/search/SearchItemDetail.tsx`
- `ui/src/components/search/contextual/DiffContext.tsx`
- `ui/src/components/search/contextual/EmailContext.tsx`
- `ui/src/components/search/contextual/MeetingContext.tsx`
- `ui/src/components/search/contextual/ChatContext.tsx`
- `ui/src/components/search/contextual/ItemContext.tsx`

**Files to modify:** None (route already added in Slice 8)

**Files to delete:** None

**Tests:**
- `ui/src/pages/Search.test.tsx` -- Empty state, auto-focus, kind filtering, result selection, item actions with toast, five UI states, keyboard navigation (arrow/enter/escape), ARIA attributes (listbox/option/activedescendant), max 100 results
- `ui/src/components/search/ResultRow.test.tsx` -- Kind icon, priority badge, active state
- `ui/src/components/search/SearchItemDetail.test.tsx` -- Header, actions bar, LLM summary, contextual payload, processing log, empty state
- `ui/src/components/search/contextual/ItemContext.test.tsx` -- Dispatches correctly per type

**Complexity:** L

**Dependencies:** Slice 4 (StateDot, SourceChip, VerdictPill), Slice 6 (FunnelStage), Slice 12 (useSearchItems hook created in `ui/src/hooks/useSearchItems.ts`)

**Parallelizable with:** Slice 12

---

## Slice 14: Overview + SourceFlow

**Title:** Clickable Hot Feed, SourceFlow Sankey, stalled source indicators

**Description:** Hot Feed items become clickable buttons opening ItemFunnelDialog (see canonical mounting pattern in Slice 6). Build SourceFlow animated Sankey (left sources, center WorkBench, right output buckets, bezier ribbons, 80-dot rAF animation pool, 2.8s traversal, spawn rate proportional to volume, visibility API pause, hover re-proportioning, stalled source detection). Client-computed flow matrix via buildFlowMatrix() from funnel-helpers.ts (Slice 1) -- the function takes per-source ingest counts and per-output-bucket counts and computes proportional ribbon weights. Add to Infrastructure section. Five UI states for SourceFlow.

**Files to create:**
- `ui/src/components/SourceFlow.tsx` -- Animated Sankey with rAF, dot pool, hover isolation, sr-only table fallback

**Files to modify:**
- `ui/src/pages/Overview.tsx` -- Hot Feed clickable (canonical ItemFunnelDialog pattern), SourceFlow in Infrastructure, stalled indicators

**Files to delete:** None

**Tests:**
- `ui/src/components/SourceFlow.test.tsx` -- Layout computation, five UI states, stalled source rendering, prefers-reduced-motion, sr-only table, click navigation
- `ui/src/pages/Overview.test.tsx` -- Hot Feed items clickable, SourceFlow present, ItemFunnelDialog opens on click

**Complexity:** L

**Dependencies:** Slice 1 (buildFlowMatrix), Slice 4 (primitives), Slice 6 (ItemFunnelDialog)

**Parallelizable with:** Slice 12, Slice 13

---

## Slice 15: MSW Handlers + Accessibility + Final Test Updates

**Title:** MSW mock handlers, accessibility test updates, cross-cutting test cleanup

**Description:** Add all new endpoint handlers to `ui/src/test/server.ts` (confirmed to exist at this path -- currently an empty setupServer() call). Update a11y.test.tsx for Settings tabs, Search listbox, LiveTail aria-live, SourceFlow role=img, FunnelStage correction picker, new dialog ARIA, ActionChip/VerdictPill color+text redundancy, ConfidenceBar ARIA, hover-expand rail. Clean up any test imports referencing deleted useWorkMode. Verify all pages pass accessibility audit.

**Files to create:** None

**Files to modify:**
- `ui/src/test/server.ts` -- Add MSW handlers for all new /api/feedback/*, /api/funnel/*, /api/enrichers/*, /api/loopbacks/*, /api/items/search, /api/items/:id/snooze, /api/filter-rules/:id/items, /api/items/:id/funnel
- `ui/src/a11y.test.tsx` -- Settings tabs ARIA, Search listbox, LiveTail, SourceFlow, FunnelStage, dialogs, color+text redundancy, hover-expand labels

**Files to delete:** None

**Tests:** This slice IS the test cleanup slice. No separate test file -- it modifies existing test infrastructure.

**Complexity:** M

**Dependencies:** All previous slices (this is the final integration/cleanup pass)

**Parallelizable with:** Nothing -- runs last

---

## Database Migrations Detail

**Migration 009 transaction order:**
1. `CREATE EXTENSION IF NOT EXISTS pg_trgm;` -- MUST execute before any GIN trigram index
2. CREATE TABLE feedback_corrections, filter_tuning_tasks, enrichers, loopbacks, funnel_stages, funnel_order
3. ALTER TABLE filter_rules ADD COLUMN prompt TEXT (nullable, added alongside existing nullable pattern column for backward compat)
4. ALTER TABLE filter_rules ADD COLUMN sources, confidence, origin, matched, enabled, label, order_index
5. `UPDATE filter_rules SET prompt = pattern WHERE prompt IS NULL AND pattern IS NOT NULL;` -- rows where both are NULL are left untouched (no prompt assigned)
6. ALTER TABLE items ADD COLUMN tags, llm_summary, enriched_context, funnel_log, verdict_*
7. CREATE INDEX idx_items_search_trgm ON items USING GIN (... gin_trgm_ops) -- pg_trgm guaranteed available from step 1

**Rollback SQL:**
1. `UPDATE filter_rules SET pattern = prompt WHERE pattern IS NULL AND prompt IS NOT NULL;` -- only backfills pattern for rows that had their pattern copied forward; does NOT overwrite rows that had an independent pattern value
2. DROP INDEX, DROP COLUMN (reverse of forward), DROP TABLE (reverse order)
3. Extension pg_trgm is left in place (extensions are cluster-wide, dropping is unsafe)

---

## Dependency Graph

```
Slice 1 (Client types)  ----+----> Slice 4 (Shared UI)  ----+
                             |                                |
                             +----> Slice 5 (Feedback store) -+---> Slice 6 (Funnel core)
                             |                                |           |
Slice 2 (Server domain) ----+----> Slice 3 (Server APIs) ----+           |
                                                                         |
                                          Slice 7 (Shell) <-- Slice 4    |
                                               |                        |
                                               v                        v
                                     Slice 8 (Settings tabs)    Slice 9 (Action Items)
                                                                Slice 10 (Triage)
                                                                         |
                                                    +--------------------+
                                                    |         |          |
                                                    v         v          v
                                         Slice 11  Slice 12  Slice 13  Slice 14
                                        (Ingestion) (Filters)  (Search) (Overview)
                                                    |         |          |
                                                    +----+----+-----+----+
                                                         |
                                                         v
                                                   Slice 15 (Tests)
```

## Parallelism Summary

| Phase | Slices Running | What |
|---|---|---|
| Phase 1 | 1 + 2 | Client types + Server domain (fully independent) |
| Phase 2 | 3 + 4 | Server APIs + Client primitives (after their respective Phase 1 deps) |
| Phase 3 | 5 + 7 | Feedback store + Shell changes (after Phase 2) |
| Phase 4 | 6 + 8 | Funnel core + Settings tabs (after Phase 3) |
| Phase 5 | 9 + 10 | Action Items + Triage (after Phase 4) |
| Phase 6 | 11 + 12 + 13 + 14 | Ingestion + Filters + Search + Overview (max parallelism, after Phase 5) |
| Phase 7 | 15 | Final test cleanup (after everything) |

## Total File Count

| Category | New | Modified | Deleted |
|---|---|---|---|
| Client (ui/src/) | 39 | 13 | 2 |
| Server (src/workbench/) | 10 | 10 | 0 |
| **Total** | **49** | **23** | **2** |

**Deleted files (2):** `ui/src/hooks/useWorkMode.ts`, `ui/src/hooks/useWorkMode.test.ts`