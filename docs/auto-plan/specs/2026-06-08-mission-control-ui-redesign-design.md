# Workbench Mission Control UI Redesign — Design Spec

> Companion to the decision log `docs/auto-plan/reports/2026-06-08-mission-control-ui-redesign-decisions.md`
> and the design reference `~/workspace/workbench-stitch-designs/DESIGN-REFERENCE.md`.
> Terms (Item, Action Item, Triage Card, Source, Pipeline Job, Preference Fact, Messenger,
> Source Health Status, UI State Taxonomy) are used per `CONTEXT.md`. All artifacts ship in the
> public OSS `workbench` repo; nothing lands in `workbench-meta`.

## Context — what exists today, what's missing, why

The Management Dashboard (`ui/src/`) is a functional eight-page React SPA wired to `/api` via TanStack Query with a generic grey shadcn theme, a flat 208px text sidebar (`AppSidebar.tsx`), and OKLCH neutral tokens hardcoded to `class="dark"`. It is correct but visually undifferentiated: no brand identity, no command palette, no derived operational metrics, no infrastructure view, and several pages render flat tables where the Stitch "mission-control" reference shows grouped, keyboard-driven, terminal-styled surfaces. This redesign reskins every page to the two-orange Stitch design, adds the icon-rail shell, a `⌘K` palette, and seven new backend endpoints that replace fabricated mockup numbers with honest derivations — preserving all data wiring, the five-state UI State Taxonomy, and WCAG AA.

## Goals

1. **Reskin** every page and shared component to the Stitch two-orange dark/light/auto theme using raw-hex tokens layered under shadcn CSS variables.
2. **Self-host** all fonts and icon dependencies so the dashboard builds and runs fully offline (no external CDN).
3. **Replace** the flat text sidebar with a 64px icon rail + sticky top app bar driven by a CSS-grid app shell.
4. **Add** a `⌘K` command palette backed by a new server-side `GET /api/search` global search across Items, Action Items, Sources, and Preference Facts.
5. **Derive** honest operational metrics (signal velocity, throughput, avg triage time, ingestion success rate) from real tables instead of fabricated mockup constants.
6. **Compose** an infrastructure topology view and a client-only Work Mode from existing health probes and localStorage.
7. **Preserve** TanStack Query wiring, HashRouter, the five-state UI State Taxonomy, ADR-mandated empty-state/auth/secret/tombstone contracts, and WCAG AA on every page.
8. **Drop** every hollow widget (active_sessions, unread pings, blocked tasks, kernel/arch/memory/network-latency, fabricated uptime) rather than re-skinning placeholders.

## Architecture

```
 next-themes ThemeProvider (attribute="class", defaultTheme="system", enableSystem)
        │  toggles .dark on <html>
        ▼
 index.css  ──  :root (light hex tokens)  +  .dark (dark hex tokens)
        │        exposed to Tailwind v4 via @theme inline → --color-* + --surface-* + --brand
        ▼
 AppShell (CSS grid [64px_1fr]/[auto_1fr])
   ├─ AppSidebar  (icon rail, NavLink + Radix tooltip, aria-current)
   ├─ TopBar      (brand, mono context label, ⌘K trigger, sync status, theme toggle, user)
   ├─ CommandPalette (cmdk, global ⌘K) ── GET /api/search ──┐
   └─ <main> (single scroll) → Pages ──────────────────────┤
                                                            ▼
   Pages call hooks/use*.ts → lib/api.ts → bearer-authed /api:
     existing: /api/stats/{overview,sources,queue,ingestion-timeseries}, /api/items,
               /api/actions, /api/triage/pending, /api/sources, /api/memory/facts, /health
     NEW:      /api/search, /api/stats/overview#metrics, /api/stats/timeseries,
               /api/topology, POST /api/actions (manual), per-source threshold config,
               POST /api/memory/facts (manual fact), /api/triage/pending#created_at
```

Data flow is one-directional: theme tokens compile into Tailwind utilities at build time; the shell renders chrome and mounts the palette; pages own their five-state gating and call hooks; `src/lib/chart-theme.ts` reads token values so charts re-theme with the palette. No page touches storage directly (Management Dashboard contract).

---

## Design Sections

### 1. Theme tokens & dark/light/auto architecture

Author all tokens as **raw hex** (not OKLCH) to match the Stitch HTML exactly and avoid orange gamut drift. `index.css` defines `:root` (light) and `.dark` (dark) variable blocks; `@theme inline` maps them to Tailwind `--color-*` utilities plus extra `--surface-*` / `--brand-*` tiers for dense tonal work.

**Dark surface ladder (corrected from the real HTML; depth via tonal tiers, NO drop shadows on in-page surfaces):**

```
surface-container-lowest  #0e0e11   inputs / log + config block bg / deepest panel
background / surface       #131316   page background
surface-container-low      #1b1b1e   low panel tier  → --card
surface-container          #1f1f22   standard card / popover → --popover
surface-container-high     #2a2a2d   raised header / active nav bg → --accent (neutral hover)
surface-container-highest  #353438   highest / pills (== surface-variant)
```

**Two-orange system (do NOT collapse to one orange):**

```
primary-container  #ff6a2b   CTAs, active rail bar, chart-primary, focus ring        (--primary)
primary            #ffb59a   headings, icons, AND the AA-safe orange for text on dark
on-primary-container #0e0e11 near-black text on orange fills                          (--primary-foreground)
```

**Text & borders:** `on-surface #e4e1e6` (body); `on-surface-variant` muted/label; hairline border **normalized to `#26262C`** (ignore the design's `#5a4138` brown drift); `outline #a98a7f` for stronger borders/muted text.

**Functional:** error text `#ffb4ab` / error fill `#93000a`; tertiary (info/links/healthy-cyan) `#71d2ff`. Green/blue/red raw Tailwind classes seen in the HTML are normalized to these tokens. `.prio-P0..P3` stay (already AA-tuned); hues retuned to harmonize with the palette but contrast ratios unchanged.

**shadcn variable map (dark):**

| shadcn var | hex | Notes |
|---|---|---|
| `--background` | `#131316` | page bg |
| `--card` | `#1b1b1e` | surface-container-low |
| `--popover` | `#1f1f22` | surface-container |
| `--primary` | `#ff6a2b` | the orange |
| `--primary-foreground` | `#0e0e11` | near-black on orange |
| `--secondary` | `#1f1f22` | — |
| `--muted` | `#1b1b1e` | + muted-foreground |
| `--accent` | `#2a2a2d` | **neutral hover, NOT brand orange** |
| `--destructive` | `#93000a` | error fill; text uses `#ffb4ab` |
| `--border` / `--input` | `#26262C` / `#0e0e11` | hairline / input bg |
| `--ring` | `#ff6a2b` | orange focus ring |

Add `--surface-{lowest,low,container,high,highest}` and `--brand`/`--brand-fg` as extra tokens exposed via `@theme inline` for tonal utilities.

**Radius:** `--radius → 0.375rem`; `--radius-lg` = 6px (cards), `--radius-md` = 4px (buttons/inputs), `--radius-sm` = 2px (chips).

**Dark default + light + auto:** mount `next-themes ThemeProvider` (`attribute="class"`, `defaultTheme="system"`, `enableSystem`) in `main.tsx`; **REMOVE** the hardcoded `class="dark"` from `index.html`. Light palette is grounded in `stitch-design-light.html`; brand orange `--primary`/`--ring` stay identical across both themes.

### 2. Typography & offline font delivery

Self-host three variable fonts **offline** via npm; Vite bundles the woff2 — NO Google Fonts CDN, NO Material Symbols CDN.

```jsonc
// new deps (SIL OFL 1.1, OSS-redistributable; latin subset, weights 400/500/600/700 via variable axis)
"@fontsource-variable/space-grotesk"
"@fontsource-variable/hanken-grotesk"
"@fontsource-variable/jetbrains-mono"
```

```css
/* index.css imports (Vite resolves to bundled woff2) */
@import "@fontsource-variable/space-grotesk";
@import "@fontsource-variable/hanken-grotesk";
@import "@fontsource-variable/jetbrains-mono";

@theme inline {
  --font-sans:    "Hanken Grotesk Variable", ui-sans-serif, system-ui;
  --font-display: "Space Grotesk Variable", var(--font-sans);
  --font-mono:    "JetBrains Mono Variable", ui-monospace, monospace;
  --text-display-lg: 32px; --text-display-sm: 24px; --text-title-md: 18px;
  --text-body-md: 14px; --text-body-sm: 13px;
  --text-mono-label: 12px; --text-mono-data: 13px;
}
```

Base layer sets `body → --font-sans`, `h1,h2,h3 → --font-display`, `font-display: swap`. The Stitch Material Symbols icons are replaced by the already-installed `lucide-react` set (no icon-font dependency).

**Mono-for-data** via a reusable `<Mono>` wrapper plus a `font-mono` escape hatch:

```tsx
// components/Mono.tsx — applies font-mono + tabular-nums
export function Mono({ children, className }: { children: ReactNode; className?: string })
```

Mono is mandatory for: numbers, timestamps, IDs, git hashes, cron expressions, code, StatCard values, DataTable metric/ID/timestamp cells, and badges/chips. jsdom cannot compute fonts, so no test asserts computed font families.

### 3. App shell: icon rail + top bar

Replace the `AppShell` flex container with a CSS grid; rail spans both rows, top bar is sticky in row1/col2, a single `<main>` scrolls.

```tsx
// AppShell.tsx
<div className="grid min-h-screen grid-cols-[64px_1fr] grid-rows-[auto_1fr]">
  <AppSidebar className="row-span-2 z-30" />   {/* full-height rail */}
  <TopBar className="sticky top-0 z-20" />
  <main className="overflow-y-auto p-6">{children}</main>
</div>
```

**64px icon rail** (`AppSidebar.tsx`), lucide 20px icons, NavLink (HashRouter-safe), `aria-current="page"` preserved (a11y.test asserts it), `aria-label` per link, Radix tooltip label per item (new dep `@radix-ui/react-tooltip`). Active = 2px `#ff6a2b` left bar + orange icon.

| Nav | route | lucide icon |
|---|---|---|
| Overview | `/` | `LayoutDashboard` |
| Triage | `/triage` | `ListChecks` |
| Action Items | `/actions` | `CircleCheckBig` |
| Ingestion | `/ingestion` | `Workflow` |
| Sources | `/sources` | `Database` |
| Knowledge | `/knowledge` | `BookOpen` |
| Messenger | `/messenger` | `MessageSquare` |
| Settings | `/settings` | `Settings` |

**Top app bar** (`components/TopBar.tsx`): brand `W` mark + "Workbench"; mono context label per route (e.g. `ACTION_ITEMS.LOG`); `⌘K` trigger slot (§4); sync-status indicator (derived from `/health`); theme toggle (light/dark/auto, three-state); user chip. The design's "Deploy" button is **dropped** (no real meaning). Rail `z-30`, top bar `sticky top-0 z-20`.

**Responsive <768px:** rail collapses to a hamburger drawer, top bar wraps/truncates. Desktop-first; mobile is secondary. `prefers-reduced-motion` gates rail/drawer transitions.

### 4. Command palette & global search (`/api/search`)

Add `cmdk` (new dep) + a vendored shadcn `command` primitive (offline). A global `(meta|ctrl)+k` listener in `AppShell` opens a Radix dialog; Esc closes; arrow/enter navigate; focus is restored to the trigger on close; a visually-hidden `DialogTitle` satisfies a11y.

**Server endpoint** — bearer-authed, new router `src/workbench/api/search.py`:

```
GET /api/search?q=<str>&limit=<int default 20, cap 50>
```

```jsonc
// response envelope
{
  "q": "rds",
  "groups": {
    "items":   [ /* SearchHit */ ],
    "actions": [ /* SearchHit */ ],
    "sources": [ /* SearchHit */ ],
    "facts":   [ /* SearchHit; omitted group when memory degraded */ ]
  },
  "truncated": false
}
// SearchHit
{ "id": "WRK-9402", "kind": "item|action|source|fact",
  "label": "...", "sublabel": "github · P0", "route": "/triage" }
```

Implementation: parameterized **ILIKE** across `items.summary`, `actions.summary` (action items), and `sources` id/adapter_type; ILIKE wildcards (`%`,`_`) in `q` are escaped. Facts are proxied from the memory service and **omitted (degraded)** when memory is `NoopMemoryLayer` or unreachable. Ranking: exact match, then prefix, then substring, then recency. No FTS/tsvector (single-user scale).

Client resolves nav **Commands** locally: 8 route jumps + "Toggle theme" + "Poll source". Debounce 200ms, min 2 chars; empty query shows Commands only. The palette renders all five UI states internally (loading / empty / error+X-Request-ID / unauthorized / degraded). Item hits route to `/triage` when the Item is `pending_triage`, else `/` (no item-detail route in v1 — flagged future).

### 5. Shared components & chart-theme

| Component | Change |
|---|---|
| `StatCard` | Mono value (large, tabular-nums) + uppercase mono-label; keep `{label,value,danger}`; add optional `delta?` and `sub?` (sparkline slot); `danger → text-destructive`. |
| `DataTable` | Add `Column.mono?: boolean` opt-in → `font-mono tabular-nums` cells; 1px row dividers (token border), no vertical borders. |
| `Card` | `rounded-md` (6px), no drop shadow; optional divided header via `border-b`. |
| `Button` | default = solid `#ff6a2b` + near-black fg; outline = 1px `#26262C` + mono label; orange ring. |
| `Badge`/chip | base `font-mono`; add `p0..p3` variants (P0 = 15% red bg + solid red border). Migrate ActionItems raw priority `<span>`s; deprecate `.prio-*` classes. |
| `Input` | bg `#0e0e11`, 1px border, optional mono. |
| `EmptyState` | terminal `// End of feed` aesthetic. |

```ts
// DataTable Column extension
export interface Column<T> {
  key: string; header: string; render: (row: T) => ReactNode;
  mono?: boolean;   // → font-mono tabular-nums on cells
}
```

**New components:** `Sparkline` (Recharts area/line), `LogStream` (mono auto-scroll terminal pane), `Mono` (§2).

```ts
// src/lib/chart-theme.ts — single token-driven export, replaces hardcoded DONUT_COLORS in Overview.tsx
export const CHART_COLORS = {
  primary: "#ff6a2b", tertiary: "#71d2ff",
  red: "#ffb4ab", amber: "#ffb59a", blue: "#71d2ff", green: "#9ad08a",
} as const;
export const CHART_DEFAULTS = { /* grid #26262C, axis on-surface-variant, tooltip surface-container, legend */ };
```

All chart pages import `CHART_COLORS`/`CHART_DEFAULTS`. Sparkline degenerate states: empty → flat baseline + "—"; single point → a dot.

### 6. Derived metrics endpoints

Add a `metrics` block to `GET /api/stats/overview` (scalars) and a generic timeseries route. No caching.

```
GET /api/stats/timeseries?metric={signal_velocity|throughput}&window=<int>&bucket={hour|day}
→ [ {"bucket": "<iso>", "count": <int>}, ... ]   // full bucket array; count:0 for empty buckets, never omitted
```

```jsonc
// added to GET /api/stats/overview
"metrics": {
  "signal_velocity":     <int|null>,   // items created per bucket, 24h/hour
  "throughput":          <int|null>,   // action items completed (completed_at) per hour, 8h
  "efficiency_peak":     <float|null>, // max bucket close-rate, ratio 0..1 (completed/created in the busiest bucket)
  "auto_resolved_pct":   <float|null>, // auto_included / all over window
  "avg_triage_seconds":  <int|null>,   // avg(triage_cards.responded_at - sent_at)
  "growth_velocity":     <int|null>,   // facts added delta over window (null/degraded under NoopMemory)
  "ingestion_success_rate": <float|null> // success_runs / total_runs over window (ingestion_runs)
}
```

**Honest derivations (no fabrication):**
- `signal_velocity` = Items created per bucket (24h window, hourly).
- `throughput` = Action Items completed (`completed_at`) per hour (8h window).
- `efficiency_peak` = the maximum bucket close-rate, a **float ratio 0..1** (completed/created within the busiest bucket); `null` when no buckets have any created items. The UI may render it as a percent.
- `auto_resolved_pct` = `auto_included / all` over the window.
- `avg_triage_seconds` = `avg(triage_cards.responded_at - sent_at)` — there is no `triaged_at` column on items.
- `growth_velocity` = facts-added delta over the window (returns `null`, rendered "n/a", under `NoopMemoryLayer`).
- **Hot feed** uses the existing list endpoint: `GET /api/items?priority=P0|P1&status=pending_triage`.
- **"Uptime" is relabeled "Ingestion success rate"** = `success_runs/total_runs` over the window from `ingestion_runs`. No uptime/health history is persisted; the fabricated `99.98%` is never rendered.

Scalars return `null` → UI renders **"n/a"** when the denominator is 0 or history is insufficient; percentage deltas are `null` when the prior window is empty.

**Dropped (hollow, no honest source — listed, not specced):** `active_sessions` (no session concept), `unread pings` (Messenger is notification-only, ADR0001), `blocked tasks` (not a real Item status).

### 7. Topology endpoint + Work Mode

New router `src/workbench/api/topology.py` composes existing health probes:

```
GET /api/topology
```

```jsonc
{
  "nodes": [ {"id":"app","label":"Workbench","kind":"app","status":"healthy"},
             {"id":"pg","label":"PostgreSQL","kind":"storage","status":"healthy"},
             {"id":"memory","label":"Memory Service","kind":"memory_service","status":"not_configured"} ],
  "edges": [ {"from":"app","to":"pg","kind":"connection"} ]
}
// kind ∈ {app, storage, memory_service, connection, adapter, messenger}
// status ∈ {healthy, degraded, unhealthy, unknown, not_configured}
```

Client polls every 15s. Rendered as a **2D hand-rolled SVG** node-link graph (NO react-three-fiber, NO reactflow), techy styling, with a table fallback for a11y (`role="img"` on the SVG + a visually-hidden `<table>` of nodes/statuses). neo4j is folded into the `memory_service` node (no standalone probe in OSS); no meta-only / dcat nodes.

**Work Mode / Terminal Focus** is a **client-only** view preference in localStorage. When ON: filter the feed/Overview to the top active P0 "vector", hide non-critical widgets, dim chrome; sync across tabs via the `storage` event; zero-active → a focused empty state. It does **NOT** mute notifications. The Stitch toggle label renders `WORK_MODE_OFF`/`WORK_MODE_ON`.

### 8. Page: Overview

Merge Stitch Overview variant B (#7, the chosen base) with the hero widgets from variant A (#2). Keep all existing 6 StatCards + 4 charts + Recent Engine Jobs table (faithful-repro, ADR0016) and **add a hero region**:

- **Attention header** — P0 active count + pending triage count (drops unread-pings/blocked-tasks).
- **HOT FEED** — high-priority pending Items list (`GET /api/items?priority=P0|P1&status=pending_triage`).
- **INITIATE TRIAGE CTA** → `/triage`, labeled with the pending count.
- **Ingestion-success-rate tile** (§6) — replaces the fabricated uptime tile.
- **INFRASTRUCTURE topology panel** (§7).
- **Queue Ingestion Status table** — reuses the `/api/stats/sources` rollup.
- **Dismissible System Alert banner** — client-dismissed; rendered only when a real degraded condition exists.

New hero widgets fail-soft inline (each renders its own degraded/empty state); the page-level five-state gate over the primary stats query is preserved. Charts use `CHART_COLORS` (§5). Work Mode (§7) hides non-critical hero widgets when ON.

### 9. Page: Triage (combined A-shell + B-cards)

Combine Stitch Triage variant A (3-column shell) with variant B (keyboard card interactions).

- **Left filter rail:** Sources checkboxes + counts, Priority filter, Time Window quad (LAST 1H / 24H / 7D / ALL) — all **client-side** filters over the fetched pending cards.
- **Center keyboard card feed (variant B):** each card shows the Item ID + relevance score, numbered options `[1][2][3]`, a free-text reply input ("Press Enter to execute"), `J`/`K` navigation, and a priority/relevance colored left border. Preserves ADR0027 free-text replies + destructive-action confirm.
- **Right analytics column:** Signal Velocity sparkline + Automation Stats (`auto_resolved_pct`, `avg_triage_seconds` from §6) + LLM Insight.
- **LLM Insight panel** is data-backed by real per-option `suggestion_reason` / `confidence` and renders **only when those fields are present** (no fake static panel).
- **Two empty states:** "Inbox zero / System Harmony" (no cards) vs "No cards match filters" (filtered to empty).

The Time Window filter keys off a real per-card **`created_at`** timestamp. The `triage_cards` table currently has only `sent_at`/`expires_at`/`responded_at`/`deferred_until` (no row-birth column), so a new migration adds `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, the `TriageCard` model gains a `created_at` field, and `GET /api/triage/pending` serializes it (the endpoint returns Pydantic `TriageCard` models — serialize via `model_dump()`). `queued_at` is **not** a separate column; the queue lifecycle is `queued → sent → responded/expired` (CONTEXT.md "Triage Queue"), so "queued" age is the row's `created_at`. The client Time Window quad (1H/24H/7D/ALL) filters fetched cards by `created_at`.

### 10. Page: Action Items (grouped + FAB / POST /api/actions)

Replace the flat DataTable with grouped sections, preserving the existing category filter + set-priority + done/snooze actions.

- **Grouping:** **ACTIVE NOW** = P0 or (P1 & age <24h); **TODAY** = remaining P1 + P2 age <7d; **LATER** = P3 + older/snoozed. Priority colored left-border rows.
- **Throughput bar** + **efficiency_peak card** from §6.
- **Terminal Focus / Work Mode card** from §7.
- **Orange FAB → manual Action Item** via a **new** `POST /api/actions` (the existing router has only GET + done/priority/snooze) and a new `useCreateAction` hook.

```jsonc
// NEW: POST /api/actions  (manual Action Item; action_source = "manual")
// request
{ "summary": "string", "priority": "P0|P1|P2|P3", "action_category": "string|null" }
// response: the created Action Item row (id, summary, priority, action_source="manual", created_at)
```

### 11. Pages: Ingestion + Sources (+ per-source relevance-threshold config drawer + LIVE log)

**Sources** (Stitch variant B, card grid): one card per real configured adapter only (github/email/calendar/chat) with `HealthBadge` (Source Health Status), last sync = `last_run`, volume sparkline = `items_stored`; a dashed **"Connect New Source"** card opens the 2-step `SourceForm` wizard (cron preview, folded from Stitch Sources variant A). Full CRUD: enable `Switch`, kebab Edit/Poll/Enable/Delete with confirm. Top StatCards: Active Pipes (enabled count), Ingestion Volume (sum `items_stored`), Errors (erroring-source count). Mockup adapter names (Jira/Slack/PagerDuty/Linear) are illustrative only and are never rendered.

**Per-source Config Drawer** with real relevance-threshold sliders → new per-source backend config fields and hot-reload:

```jsonc
// new per-source SourceConfig fields (written via Config Write-Back + Targeted Hot-Reload)
"relevance": {
  "auto_include_threshold": <float 0..1>,  // ≥ → auto-include at active
  "triage_threshold":       <float 0..1>,  // ≥ → send to triage
  "drop_below":             <float 0..1>   // < → drop as noise
}
```

The drawer's "Noise Filter" sliders bind to these fields (PATCH `/api/sources/{id}` round-tripped to `config.yml` per Config Write-Back; live adapter swapped via Targeted Hot-Reload).

**Ingestion** (ops surface, NOT merged with Sources): keep per-source panels, Recent Activity, Job History (filter + pagination), Queue Health (StatCards + bar), Dead Letters (Retry/Purge with confirm), all restyled, and **add a LIVE INGESTION LOG** = `useActivity` polled every 15s rendered through the new `LogStream` component.

**Dropped/relabeled:** System Latency (no timing exposed — dropped; the "last sync age" is shown instead); a true Errors-24h aggregate is replaced by the erroring-source-count proxy.

### 12. Pages: Knowledge (+manual fact) + Messenger + Settings (+JSON highlighter)

**Knowledge:** StatCards Total Facts (`facts.length`), Active Sources (`sources_enabled`), Growth Velocity — the **scalar** `metrics.growth_velocity` delta from `GET /api/stats/overview` (§6), rendered as a single StatCard number, **n/a, not fake**, under `NoopMemoryLayer`. There is NO facts timeseries: `/api/stats/timeseries` only serves `signal_velocity|throughput` (§6), so Growth Velocity is a scalar StatCard with no sparkline series; a facts TABLE with source pills + date (`Fact.timestamp`, em-dash when null); a GROUP BY SOURCE toggle. **Add Fact** button → manual Preference Fact create:

```jsonc
// NEW: POST /api/memory/facts  (manual fact; origin distinct from learned; 501 under NoopMemoryLayer)
{ "content": "string", "source": "string|null" }
```

Manual facts coexist with ADR0019 tombstones (manual origin distinct from learned). Preserve edit/delete + degraded states. (The current `Knowledge.tsx` has no Overview/Metrics/Logs tabs — there is nothing to drop; the net-new work is Add Fact + Growth Velocity + StatCards.)

**Settings:** keep App Version (`health.version`) + Config Version + Subsystem Health badges; JSON config blocks (pipeline/scheduler/retention/alerting) with a **lightweight regex → React-span syntax highlighter** (no shiki/prismjs, no `dangerouslySetInnerHTML`):

```tsx
// components/JsonHighlight.tsx — regex-split JSON into <span> tokens with re-themed token colors
// keys → primary(#ffb59a), strings → tertiary(#71d2ff), numbers → on-surface, punctuation → on-surface-variant
function JsonHighlight({ json }: { json: string }): ReactElement
```

The design's low-contrast JSON colors (`#003648`/`#5c1b00`) are re-themed to the AA-safe tokens above. `CONFIG_SECRETS` panel stays locked (secrets never rendered, ADR0017). **DOWNLOAD BACKUP** = a client `Blob` of the already-redacted `GET /api/debug/config`. **Drop the vanity Runtime Metadata** (kernel/arch/memory/network-latency — no data source); process Uptime is shown only if a real start-time is exposed, else dropped.

**Messenger:** restyle to tokens; preserve the non-secret-only read (space_id, timeout_seconds) + reachability badge + RHF/Zod edit form + the "no messenger" degraded state.

### 13. Accessibility & contrast contract

`#ff6a2b` as small text passes AA on base surfaces (`#0e0e11` 6.74:1, `#1b1b1e` ~6:1) but FAILS on elevated surfaces (≥ ~`#303038`) and as white-on-orange (2.86:1). Rules, enforced in components:

- Orange text (`#ff6a2b`) only on surfaces ≤ `#2a2a2d`.
- On orange fills, foreground is near-black (`on-primary-container #0e0e11`).
- On elevated / popover / tooltip surfaces, use `on-surface` body text or the lighter `#ffb59a` orange for accents (never `#ff6a2b` as text there).
- Focus ring is orange `#ff6a2b`, 2px outline + 2px offset (baseline preserved from `index.css`).
- `.prio-*` priority classes stay AA in both themes.

ARIA preserved: nav landmark + `aria-label` per rail link + `aria-current="page"`; palette `combobox`/`listbox` roles + focus trap/restore; error states surface `X-Request-ID`.

### 14. Testing strategy

- Update each co-located `*.test.tsx` alongside its page (NO centralized render-helper refactor mid-flight).
- One shared MSW handler module covers the new `/api/search`, `/api/stats/timeseries`, `/api/stats/overview#metrics`, `/api/topology`, `POST /api/actions`, `POST /api/memory/facts`, per-source threshold config, and the `/api/triage/pending` timestamp fields.
- Extend `a11y.test.tsx` for: the rail (nav landmark, `aria-label`, `aria-current`), `⌘K` (combobox/listbox roles, focus trap + restore), and the theme toggle.
- No test asserts computed fonts (jsdom limitation).
- Backend endpoints tested via pytest (`make test`): search ranking + ILIKE escaping + facts-degraded, metrics derivations + null-on-empty, timeseries zero-fill, topology composition, manual action + manual fact (incl. 501 under NoopMemory), per-source threshold write-back.

### 15. Build, new deps & rollout ordering

**New deps (all bundled offline via Vite; Tailwind v4 `@theme` compiles at build time):**

```
@fontsource-variable/space-grotesk
@fontsource-variable/hanken-grotesk
@fontsource-variable/jetbrains-mono
cmdk
@radix-ui/react-tooltip
```

`next-themes`, `recharts`, and `lucide-react` are already dependencies — reused, not added. Makefile `ui-build` / `ui-test` targets are unchanged (ADR0020); Make remains the dev interface.

**Rollout (foundation-first; `make ui-test` green per commit; single-user → no feature flags):**

1. Tokens + contrast contract in `index.css` (+ remove `class="dark"` from `index.html`, mount ThemeProvider).
2. Fonts + `Mono`.
3. Primitives/components: tooltip, Button, Badge, Card, DataTable, Sparkline, LogStream, chart-theme.
4. Shell: icon rail → top bar → theme toggle → `⌘K` + `/api/search`.
5. Backend endpoints: metrics, timeseries, topology, `POST /api/actions`, triage timestamp, per-source thresholds, manual fact, search (+ MSW handlers).
6. Pages, in order: Overview → Triage → Action Items → Sources → Ingestion → Knowledge → Settings → Messenger.

`prefers-reduced-motion` gates rail/palette animation throughout.

---

## File Changes

### Frontend — new files (`ui/src/...`)

| File | Purpose |
|---|---|
| `components/TopBar.tsx` | Sticky top app bar (brand, context label, ⌘K trigger, sync, theme toggle, user) |
| `components/CommandPalette.tsx` | cmdk palette + global ⌘K listener + local Commands |
| `components/ui/command.tsx` | Vendored shadcn cmdk primitive |
| `components/ui/tooltip.tsx` | Vendored shadcn Radix tooltip primitive |
| `components/Mono.tsx` | font-mono + tabular-nums wrapper |
| `components/Sparkline.tsx` | Recharts area/line sparkline + degenerate states |
| `components/LogStream.tsx` | Mono auto-scroll terminal log pane |
| `components/Topology.tsx` | 2D SVG node-link graph + a11y table fallback |
| `components/JsonHighlight.tsx` | Regex → React-span JSON highlighter |
| `components/ThemeToggle.tsx` | Three-state light/dark/auto toggle |
| `lib/chart-theme.ts` | `CHART_COLORS` + `CHART_DEFAULTS` |
| `hooks/useSearch.ts` | `GET /api/search` |
| `hooks/useTopology.ts` | `GET /api/topology` (poll 15s) |
| `hooks/useWorkMode.ts` | localStorage + `storage`-event view preference |
| `hooks/useActivity.ts` | LIVE log polling (15s) |
| `test/handlers.ts` | Shared MSW handlers for new endpoints |

### Frontend — modified files (`ui/src/...`)

| File | Change |
|---|---|
| `main.tsx` | Mount `next-themes` ThemeProvider |
| `index.html` | Remove hardcoded `class="dark"` |
| `index.css` | Replace OKLCH tokens with hex two-orange ladder + `@theme inline` + font imports |
| `components/AppShell.tsx` | flex → CSS grid; mount TopBar + CommandPalette |
| `components/AppSidebar.tsx` | 64px icon rail, lucide icons, tooltips, active bar |
| `components/StatCard.tsx` | Mono value + `delta?`/`sub?` |
| `components/DataTable.tsx` | `Column.mono?` |
| `components/ui/{card,button,badge,input}.tsx` | Token restyle; badge p0..p3 variants |
| `components/EmptyState.tsx` | Terminal aesthetic |
| `pages/Overview.tsx` | Hero region; drop DONUT_COLORS for chart-theme |
| `pages/Triage.tsx` | 3-column + keyboard cards + filters + LLM Insight |
| `pages/ActionItems.tsx` | Grouped sections + FAB + throughput + Work Mode |
| `pages/Sources.tsx` | Card grid + config drawer + thresholds |
| `pages/Ingestion.tsx` | Restyle + LIVE log |
| `pages/Knowledge.tsx` | Add Fact + growth velocity StatCard |
| `pages/Settings.tsx` | JSON highlighter + drop Runtime Metadata |
| `pages/Messenger.tsx` | Token restyle |
| `a11y.test.tsx` + each `pages/*.test.tsx`, `components/SourceForm.test.tsx` | Extend for new shell/palette/endpoints |

### Backend — new/modified files (`src/workbench/...`)

| File | Change |
|---|---|
| `api/search.py` | **NEW** `GET /api/search` |
| `api/topology.py` | **NEW** `GET /api/topology` |
| `api/stats.py` | Add `metrics` block to `/overview`; add `GET /api/stats/timeseries` |
| `api/actions.py` | Add `POST /api/actions` (manual Action Item) |
| `migrations/versions/007_triage_created_at.py` | **NEW** add `triage_cards.created_at TIMESTAMPTZ NOT NULL DEFAULT now()` (down_revision `006`) |
| `models.py` (`TriageCard`) | Add `created_at: datetime = Field(default_factory=...)` field |
| `storage/postgres/triage.py` | Persist + read `created_at` in `save_card` / `_row_to_card` |
| `api/triage.py` | Serialize `created_at` in `/triage/pending` payload (return `card.model_dump()` per card) |
| `api/memory.py` | Add `POST /api/memory/facts` (manual fact; 501 under NoopMemory) |
| `api/sources.py` | Per-source relevance threshold fields in PATCH + hot-reload |
| `main.py` (router registration, ~lines 271-290) | Register `search` + `topology` routers |
| repositories (items/triage/ingestion_runs) | New aggregate methods for metrics + timeseries |
| `tests/` (pytest) | Cover all new endpoints + derivations |

## Verification

1. **Done when** `index.html` has no `class="dark"`, `next-themes` is mounted, and toggling light/dark/auto switches the palette with brand orange `--ring` constant in both themes.
2. **Done when** the app builds and runs with no network access (no `fonts.googleapis.com` / `cdn.tailwindcss.com` requests) and all three fonts render from bundled woff2.
3. **Done when** the shell is a 64px icon-rail grid with lucide icons, Radix tooltips, an orange 2px active bar, and `a11y.test.tsx` asserts nav landmark + `aria-label` + `aria-current="page"`.
4. **Done when** `⌘K` opens the palette, queries `GET /api/search` (debounced, min 2 chars), shows grouped Items/Actions/Sources/Facts, omits the facts group under NoopMemory, restores focus on close, and exposes combobox/listbox roles.
5. **Done when** `GET /api/stats/overview` returns the `metrics` block with `null` (rendered "n/a") on empty denominators, and `ingestion_success_rate` is computed from `ingestion_runs` (never a literal `99.98%`).
6. **Done when** `GET /api/stats/timeseries?metric=signal_velocity&bucket=hour` returns a full, zero-filled bucket array.
7. **Done when** `GET /api/topology` returns nodes/edges composed from live probes, neo4j folded into `memory_service`, rendered as 2D SVG with a visually-hidden a11y table.
8. **Done when** Work Mode persists in localStorage, dims non-critical widgets, syncs across tabs via the `storage` event, and never mutes notifications.
9. **Done when** Overview shows the hero region (attention header, HOT FEED, INITIATE TRIAGE, ingestion-success tile, topology panel, queue table, dismissible alert) with each widget failing soft.
10. **Done when** Triage is 3-column with keyboard `J`/`K` + `[1][2][3]` cards, client filters incl. Time Window (backed by the new `triage_cards.created_at` column), a data-backed LLM Insight, and two distinct empty states.
11. **Done when** Action Items renders ACTIVE NOW/TODAY/LATER groups and the FAB creates a manual Action Item via `POST /api/actions`.
12. **Done when** Sources is a card grid with per-source relevance-threshold sliders that write back to `config.yml` and hot-reload, and Ingestion shows a 15s-polled LIVE log via `LogStream`.
13. **Done when** Knowledge "Add Fact" creates a manual Preference Fact (501 under NoopMemory) and Settings renders the regex JSON highlighter (no `dangerouslySetInnerHTML`) with the secrets panel locked and Runtime Metadata removed.
14. **Done when** every dropped hollow widget (active_sessions, unread pings, blocked tasks, kernel/arch/memory/network-latency, fabricated uptime) is absent from the rendered UI.
15. **Done when** `make ui-test` and `make test` are green, and no orange text appears on surfaces > `#2a2a2d` (contrast contract).

## Resolved Questions

1. **Token authoring format:** → Raw hex, not OKLCH. Matches the Stitch HTML exactly and avoids orange gamut drift across the two-orange system.
2. **One orange or two:** → Two. `#ff6a2b` (CTAs/active/chart/ring) and `#ffb59a` (headings/icons/AA-safe text on dark) are distinct roles; collapsing them breaks the contrast contract.
3. **Hairline border color:** → `#26262C`. The `#5a4138` warm-brown in 7 of the 11 Stitch configs is a Stitch export artifact; normalize to the cool hairline used by the Overview/Ingestion configs.
4. **Theme default:** → `system` (auto) with a three-state toggle, dark as the visual baseline. The Stitch files have no toggle; we add one.
5. **Fonts offline:** → Self-host via `@fontsource-variable/*`; no Google Fonts/Material Symbols CDN. Material Symbols are replaced by the already-bundled `lucide-react`.
6. **Search backend vs client-only:** → Server `GET /api/search` (ILIKE, no FTS) plus locally-resolved nav Commands. FTS/tsvector is unjustified at single-user scale.
7. **Search item-hit routing:** → `/triage` when `pending_triage`, else `/`. No `/items/:id` route in v1 (future).
8. **"Uptime" metric:** → Relabeled "Ingestion success rate" = `success_runs/total_runs`. No uptime history is persisted; the fabricated `99.98%` is dropped. [User: build the honest version.]
9. **Avg triage time source:** → `avg(triage_cards.responded_at - sent_at)`; there is no `triaged_at` column on items.
10. **Topology renderer:** → Hand-rolled 2D SVG (not react-three-fiber, not reactflow) with an a11y table fallback; neo4j folded into the `memory_service` node.
11. **Work Mode scope:** → Client-only localStorage visual preference with cross-tab `storage` sync; does NOT mute notifications. [User: client-only confirmed.]
12. **Triage interaction model:** → Combine variant A's 3-column shell with variant B's keyboard cards (relevance, `[1][2][3]`, free-text reply, `J`/`K`).
13. **Noise filter realness:** → Real per-source relevance thresholds (auto-include / triage / drop) persisted to `config.yml` and hot-reloaded. [User: build it real.]
14. **Add-Action / Add-Fact FABs:** → Real `POST /api/actions` (manual Action Item) and `POST /api/memory/facts` (manual fact, distinct origin, 501 under NoopMemory). [User: build both.]
15. **JSON highlighter library:** → Lightweight regex → React-span (no shiki/prismjs, no `dangerouslySetInnerHTML`); re-theme the low-contrast Stitch colors.
16. **Sources vs Ingestion:** → Two separate pages — Sources is the card-grid management surface (variant B); Ingestion stays the ops surface (panels, job history, dead letters) + a LIVE log.

## Out of Scope

- Item-detail route (`/items/:id`) for search hits — search routes to `/triage` or `/` for now.
- Backend notification suppression / quiet-hours — only relevant if Work Mode should ever mute notifications; currently it does not.
- A standalone neo4j topology node — folded into the `memory_service` node.
- Visual-regression testing tooling (VRT).
- Mockup-only source adapters (Jira/Slack/PagerDuty/Linear) — illustrative; only real configured adapters (github/email/calendar/chat) render.
- The Stitch "Deploy" button and `sensors`/`memory`/`dns` top-bar status icons — no real meaning; dropped.
- A true **Errors-24h aggregate** (count of erroring ingestion runs in the last 24h). Resolved to the **erroring-source-count proxy** (number of sources currently in an error Health Status) on Sources/Ingestion; a real 24h aggregate from `ingestion_runs` is deferred (no new endpoint in v1).
