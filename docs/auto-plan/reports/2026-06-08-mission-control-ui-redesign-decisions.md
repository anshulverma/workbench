# Mission Control UI Redesign — Consolidated Decision Log

Source of truth for the spec/plan writers and hardening passes. Synthesized from 11 grilling
sub-agents + the real design HTML (`workbench/stitch-design.html` dark, `stitch-design-light.html`
light; distilled in `~/workspace/workbench-stitch-designs/DESIGN-REFERENCE.md`) + user
clarifications (2026-06-08).

## Global settled facts
- All UI + planning artifacts live in the **public OSS `workbench` repo**. NOTHING in `workbench-meta`.
- Preserve TanStack Query data wiring, accessibility (focus rings, ARIA, WCAG AA), and the
  five-state taxonomy (loading / error+X-Request-ID / empty / unauthorized / degraded) on every page.
- HashRouter (ADR0018); read-API empty-state contract (ADR0016); auth/secret model (ADR0017);
  messenger notification-only (ADR0001); fact curation tombstones (ADR0019); Make is the dev
  interface (ADR0020). Offline deploy: no external CDN.
- Real source adapters only: github/email/calendar/chat. Mockup names (Jira/Slack/PagerDuty/Linear)
  are illustrative — render only configured adapters.
- The two `stitch-design*.html` files are gitignored design references, not shipped.

## b001 — Theme tokens & dark/light architecture
- Author tokens as **raw hex** (not OKLCH) to match the design exactly and avoid orange gamut drift.
- **Surface ladder (corrected from real HTML):** `surface-container-lowest #0e0e11` < `background/surface #131316` (page bg) < `surface-container-low #1b1b1e` < `surface-container #1f1f22` < `surface-container-high #2a2a2d` < `surface-container-highest/variant #353438`. Depth via tonal layers, NO drop shadows.
- **Two-orange system:** `primary-container #ff6a2b` = CTAs/active-bar/chart-primary/focus; `primary #ffb59a` = headings/icons AND the AA-safe orange for text on dark. `on-primary-container #0e0e11` (near-black) on orange fills.
- **Text:** `on-surface #e4e1e6`; `on-surface-variant` muted; `outline #a98a7f` / hairline border **normalized to `#26262C`** (ignore the design's `#5a4138` brown drift).
- **Functional:** error `#ffb4ab`/container `#93000a`; tertiary (info/links) `#71d2ff`. Keep `.prio-P0..P3` (already AA-tuned), retune hues to harmonize.
- **shadcn var mapping:** `--background→#131316`, `--card→#1b1b1e`, `--popover→#1f1f22`, `--primary→#ff6a2b` + `--primary-foreground→#0e0e11`, `--secondary→#1f1f22`, `--muted→#1b1b1e`/muted-fg, `--accent→#2a2a2d` (neutral hover — NOT brand orange), `--destructive→`error red, `--border/--input→#26262C`/`#0e0e11`, `--ring→#ff6a2b`. Add extra `--surface-*`/`--brand` tokens exposed via `@theme inline` for dense tonal utilities.
- **--radius → 0.375rem** (6px cards via `--radius-lg`; 4px buttons/inputs via `--radius-md`; 2px chips via `--radius-sm`).
- **Dark default + light + auto:** mount `next-themes ThemeProvider` (attribute="class", defaultTheme="system", enableSystem) in main.tsx; REMOVE the hardcoded `class="dark"` from index.html. Light palette grounded in `stitch-design-light.html` (the new light reference); brand orange primary/ring in both themes.
- ADR: token architecture (hex + extended Material tiers under shadcn vars); theme-default-system-with-toggle.

## b002 — Typography & font delivery
- Self-host **offline** via `@fontsource-variable/space-grotesk`, `@fontsource-variable/hanken-grotesk`, `@fontsource-variable/jetbrains-mono` (latin subset, weights 400/500/600/700 covered by variable axis). Import in index.css; Vite bundles. NO Google Fonts CDN. SIL OFL 1.1 (OSS-redistributable).
- `@theme inline`: `--font-sans=Hanken Grotesk Variable`, `--font-display=Space Grotesk Variable`, `--font-mono=JetBrains Mono Variable`. Base layer: `body→sans`, `h1-h3→display`.
- **Mono-for-data** via a reusable `<Mono>` wrapper (font-mono + tabular-nums) AND `font-mono` utility escape hatch. Mandatory for: numbers, timestamps, IDs, git hashes, cron exprs, code, StatCard values, DataTable metric/ID/timestamp cells, badges/chips. `font-display: swap`.
- Type scale as Tailwind `--text-*` tokens (display-lg/sm, title-md, body-md/sm, mono-label/data).
- ADR: self-host-fonts-offline.

## b003 — App shell: icon rail + top app bar
- Replace AppShell flex with CSS grid `grid-cols-[64px_1fr] grid-rows-[auto_1fr]`; rail `row-span-2` full height; sticky top bar in row1/col2; single scrollable `<main>`.
- **64px icon rail**, lucide 20px icons: Overview=`LayoutDashboard`, Triage=`ListChecks`, Action Items=`CircleCheckBig`, Ingestion=`Workflow`, Sources=`Database`, Knowledge=`BookOpen`, Messenger=`MessageSquare`, Settings=`Settings`. Active = 2px orange left bar + orange icon. Fixed 64px + Radix tooltip label (add `@radix-ui/react-tooltip`); `aria-label` per link; preserve `aria-current="page"` (a11y.test asserts it). Keep NavLink (HashRouter-safe).
- **Top app bar:** brand `W` mark + "Workbench", mono context label (e.g. `ACTION_ITEMS.LOG`), ⌘K trigger slot (b004), sync-status indicator, theme toggle (light/dark/auto), user. Drop the design's "Deploy" button (no real meaning). `sticky top-0 z-20` (rail z-30).
- Responsive <768px: rail → drawer/hamburger, top bar wraps/truncates (mobile is secondary; desktop-first).
- ADR: icon-rail-nav-with-tooltips; app-shell-grid-layout.

## b004 — ⌘K command palette & global search
- Add **`cmdk` + shadcn `command`** (vendored, offline). Global `(meta|ctrl)+k` listener in AppShell; Esc close; arrow/enter; focus restore; hidden DialogTitle for a11y.
- **Server `GET /api/search?q=&limit=`** (default 20, cap 50), bearer-auth, grouped envelope `{q, groups:{items,actions,sources,facts}, truncated}`; `SearchHit={id,kind,label,sublabel?,route}`. **ILIKE** across `items.summary`, `actions.summary`, `sources` id/adapter_type; facts proxied from memory service, omitted (degraded) when memory noop/unreachable. Ranking: exact/prefix before substring, then recency. Parameterized SQL; escape ILIKE wildcards. No FTS/tsvector (single-user scale).
- Client resolves nav **Commands** (8 routes + toggle theme + poll-source) locally. Debounce 200ms, min 2 chars; empty query shows Commands. Five-state inside palette (loading/empty/error/unauthorized/degraded).
- Item hits route to `/triage` if pending else `/` (no item-detail route yet — flagged future).
- ADR: server-side-global-search-endpoint; cmdk-command-palette.

## b005 — Shared components & charts
- **StatCard:** mono value (large, tabular-nums) + uppercase mono-label; keep `{label,value,danger}`; add optional `delta?` + `sub?` (sparkline slot). danger→`text-destructive`.
- **DataTable:** add `Column.mono?: boolean` (explicit opt-in) → `font-mono tabular-nums` cells; no vertical borders (already none), 1px row dividers, token border color.
- **Card:** `rounded-md` (6px), drop shadow; optional divided header (`border-b`).
- **Button:** default=solid `#ff6a2b` + near-black fg; outline=1px `#26262C` + mono label; ring orange. **Badge/chip:** base `font-mono`; add `p0..p3` variants (P0 = 15% red bg + solid red border) — migrate ActionItems raw spans + deprecate `.prio-*` classes. **Input:** bg `#0e0e11`, 1px border, optional mono. **EmptyState:** terminal `// End of feed` aesthetic.
- **New components:** `Sparkline` (Recharts area/line), `LogStream` (mono auto-scroll terminal), `Mono` wrapper.
- **`src/lib/chart-theme.ts`:** single export of token-driven `CHART_COLORS` (orange primary + cyan tertiary + semantic red/amber/blue/green) + Recharts dark defaults (grid/axis/tooltip/legend) — replaces hardcoded `DONUT_COLORS`; imported by all chart pages. Sparkline degenerate states: empty→flat baseline + "—"; single point→dot.
- ADR: chart-theme-module; datatable-mono-column; p0-chip-tinted-bordered.

## b006 — Derived metrics (backend)
- Add `metrics` block to `GET /api/stats/overview` (scalars) + generic `GET /api/stats/timeseries?metric={signal_velocity|throughput}&window=&bucket={hour|day}` (full bucket array, count:0 for empty buckets, never omit; mirrors existing ingestion-timeseries). No caching.
- **Honest derivations:** signal_velocity = items created per bucket (24h/hour); throughput = action items completed (`completed_at`) per hour (8h); efficiency_peak = max bucket close-rate as a **float ratio 0..1** (completed/created in the busiest bucket; `null` when no created items); auto_resolved% = `auto_included / all` over window; **avg triage time = avg(triage_cards.responded_at - sent_at)** (NO `triaged_at` on items); growth_velocity = facts added delta over window (degraded under NoopMemory); hot feed = `GET /api/items?priority=P0|P1&status=pending_triage`.
- **"Uptime" → relabel "Ingestion success rate"** = `success_runs/total_runs` over window from `ingestion_runs` (no uptime/health history persisted; do NOT fabricate 99.98%). [User: build honest version.]
- Scalars return `null`→render "n/a" when denominator 0 / insufficient history. % deltas null when prior window empty.
- **DROP (hollow, no honest source):** active_sessions (no session concept), unread pings (messenger notification-only), blocked tasks (not a real status).
- ADR: derived-metrics-endpoint-shape; ingestion-success-rate-not-uptime; triage-time-from-triage-cards.

## b007 — Infra topology + work mode (backend/client)
- **`GET /api/topology`** composing existing probes → `{nodes:[{id,label,kind,status}], edges:[{from,to,kind}]}`; kind∈{app,storage,memory_service,connection,adapter,messenger}; status∈{healthy,degraded,unhealthy,unknown,not_configured}. Poll 15s. Render **2D hand-rolled SVG** node-link graph (NO react-three-fiber, NO reactflow) styled techy; table fallback for a11y (`role="img"` + visually-hidden table). neo4j folded into memory_service node (no standalone probe in OSS). No meta-only/dcat nodes.
- **Work Mode / Terminal Focus:** client-only localStorage view preference; on → filter feed/Overview to top active P0 "vector", hide non-critical widgets, dim chrome; multi-tab sync via `storage` event; zero-active → focused empty state. Does NOT mute notifications. [User: client-only confirmed.]
- ADR: topology-from-health-2d-svg; work-mode-client-only-visual.

## b008 — Pages: Overview + Triage
- **Overview** (merge design variants A+B): keep all existing 6 StatCards + 4 charts + Recent Jobs (faithful-repro, ADR0016) and ADD a hero region — Attention header (P0 active, pending triage; drop unread-pings/blocked), HOT FEED (high-priority pending items list), INITIATE TRIAGE CTA (→/triage w/ pending count), Ingestion-success-rate tile (b006), INFRASTRUCTURE topology panel (b007), Queue Ingestion Status table (reuse sources rollup), dismissible System Alert banner. New widgets fail-soft inline; page-level five-state gates preserved.
- **Triage** = **combine A shell + B cards**: left filter rail (Sources checkboxes+counts, Priority, Time Window — client-side filters over fetched pending cards), center keyboard card feed (B: ID + relevance, `[1][2][3]` numbered options, free-text reply "Press Enter", J/K nav, preserve ADR0027 text replies + destructive confirm + priority/relevance left-border), right analytics column (Signal Velocity + Automation Stats from b006 + LLM Insight). Two empties: "Inbox zero/System Harmony" (no cards) vs "No cards match filters" (filtered).
- **LLM Insight panel:** back with real per-option `suggestion_reason`/`confidence` (NOT a fake static panel); render only when backed.
- **Time-window filter** needs a per-card timestamp → `triage_cards` has no row-birth column, so add a real `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` column (new migration `007`, down_revision `006`), a `TriageCard.created_at` field, and serialize it on the `/api/triage/pending` payload. No `queued_at` column (queue lifecycle `queued → sent → responded/expired`; "queued" age = `created_at`). [User: build time filter, do it right — avoid future migrations.]
- ADR: triage-three-column-layout-with-client-filters; overview-additive-hero-region.

## b009 — Pages: Action Items + Ingestion + Sources
- **Action Items:** replace flat DataTable with grouped sections **ACTIVE NOW / TODAY / LATER** (ACTIVE NOW=P0 or (P1 & age<24h); TODAY=rest P1 + P2 age<7d; LATER=P3 + older/snoozed), priority left-border rows, preserve category filter + set-priority + done/snooze; Throughput bar + efficiency_peak card (b006); Terminal Focus/Work Mode card (b007); **orange FAB → manual action** via new **`POST /api/actions`** + `useCreateAction`. [User: build Add-Action FAB.]
- **Sources** (card grid): one card per real adapter (HealthBadge, last sync=`last_run`, volume sparkline=`items_stored`) + "Connect New Source" dashed card → 2-step SourceForm wizard (cron preview); CRUD (enable Switch, kebab Edit/Poll/Enable/Delete + confirm); **per-source Config Drawer with real noise/relevance threshold sliders** → new backend per-source config fields (auto-include vs triage vs drop thresholds) + hot-reload. Top StatCards: Active Pipes (enabled count), Ingestion Volume (sum items_stored), Errors (erroring-source count). [User: build noise filter real.]
- **Ingestion** (ops, not merged): keep per-source panels, Recent Activity, Job History (filter+pagination), Queue Health (StatCards+bar), Dead Letters (Retry/Purge confirm) restyled + ADD **LIVE INGESTION LOG** = `useActivity` polled 15s → `LogStream` component.
- **DROP/flag:** System Latency (no timing exposed — drop or relabel "last sync age"); true Errors-24h aggregate (use erroring-source-count proxy unless a small aggregate is added).
- ADR: sources-cardgrid-vs-ingestion-ops-split; live-ingestion-log-polled-activity; action-items-grouped-sections; per-source-relevance-threshold-config.

## b010 — Pages: Knowledge + Messenger + Settings
- **Knowledge:** StatCards Total Facts (`facts.length`), Active Sources (`sources_enabled`), Growth Velocity = the **scalar** `metrics.growth_velocity` delta from `/api/stats/overview` (b006; degraded under NoopMemory — render n/a not fake; NO facts timeseries — `/api/stats/timeseries` serves only signal_velocity|throughput); facts TABLE with source pills + date (`Fact.timestamp`, em-dash if null); GROUP BY SOURCE toggle; **Add Fact** button → manual fact create (new path; manual origin distinct from learned; coexists with ADR0019 tombstones) [User: build Add-Fact]; preserve edit/delete + degraded states (no Overview/Metrics/Logs tabs exist to drop).
- **Settings:** keep App Version (`health.version`) + Config Version + Subsystem Health badges; **JSON config blocks** (pipeline/scheduler/retention/alerting) with **lightweight regex→React-span syntax highlighter** (no shiki/prismjs, no dangerouslySetInnerHTML; re-theme the design's low-contrast JSON colors); CONFIG_SECRETS locked panel (never render secrets, ADR0017); **DOWNLOAD BACKUP** = client Blob of already-redacted `/api/debug/config`. **DROP vanity Runtime Metadata** (kernel/arch/memory/network-latency — no data); optionally keep process Uptime only if a start-time is exposed (else drop).
- **Messenger:** restyle to tokens; preserve non-secret-only read (space_id, timeout_seconds) + reachability badge + RHF/Zod edit + "no messenger" degraded.
- ADR: json-config-regex-highlight; manual-fact-distinct-origin; redacted-config-download.

## b011 — Accessibility, testing & build/migration
- **Contrast contract:** `#ff6a2b` as small text passes AA on base surfaces (#0e0e11 6.74:1, #1b1b1e ~6:1) but FAILS on elevated (≥~#303038) and white-on-orange (2.86:1). Rules: orange text only on surfaces ≤`#2a2a2d`; on orange fills use near-black fg; on elevated/popover/tooltip surfaces use `on-surface` text or the lighter `#ffb59a` orange; orange focus ring (2px outline + 2px offset baseline kept). `.prio-*` stay AA.
- **Testing:** update each co-located `*.test.tsx` alongside its page (NO centralized render-helper refactor mid-flight); one shared MSW handler module for new `/api/search`, `/api/stats/*`, `/api/topology`, `/api/actions`, `/api/triage/pending` timestamp; extend a11y.test.tsx for rail (nav landmark, aria-label, aria-current) + ⌘K (combobox/listbox roles, focus trap/restore) + theme toggle; no test asserts computed fonts (jsdom). Backend endpoints tested via pytest (`make test`).
- **Build:** @fontsource + cmdk + @radix-ui/react-tooltip bundle offline via Vite; Tailwind v4 `@theme` compile-time; Makefile `ui-build`/`ui-test` unchanged (ADR0020). New deps: `@fontsource-variable/{space-grotesk,hanken-grotesk,jetbrains-mono}`, `cmdk`, `@radix-ui/react-tooltip`.
- **Rollout (foundation-first, `make ui-test` green per commit, single-user → no flags):** (1) tokens + contrast contract in index.css; (2) fonts + Mono; (3) primitives/components (tooltip, button, badge, Card, DataTable, Sparkline, LogStream, chart-theme); (4) shell (icon rail → top bar → theme toggle → ⌘K + /api/search); (5) backend endpoints (metrics, timeseries, topology, actions, triage timestamp, per-source thresholds, manual fact, search) + MSW; (6) pages in order Overview → Triage → Action Items → Sources → Ingestion → Knowledge → Settings → Messenger. `prefers-reduced-motion` gates rail/palette animation.
- ADR: contrast-contract-orange-on-dark; redesign-rollout-ordering.

## Open / future (explicitly out of scope of v1)
- Item-detail route (`/items/:id`) for search hits — search routes to /triage|/ for now.
- Backend notification suppression / quiet-hours (only if Work Mode should ever mute — currently no).
- Standalone neo4j topology node (folded into memory_service).
- Visual-regression testing tooling.
