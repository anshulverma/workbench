# Planning Report: Mission Control UI Redesign

Reskin + extend the Workbench web UI (`ui/`) to the dark, orange, mono/techy "Mission Control"
developer-console aesthetic from the Stitch designs, wiring real backend data behind every kept
widget.

## Execution Stats
- Mode: `--harden --max-passes 10`, confidence threshold `medium`
- Sub-agents spawned: ~30 (11 grillers, 1 design-HTML extractor, 1 spec writer + 1 spec reviewer, 1 ADR writer, 1 plan writer + 1 plan reviewer, 2 hardening passes + orchestrator verification)
- Grilling iterations: 1 (all 11 branches resolved in one parallel round)
- Hardening passes: 3 (converged)
- Questions auto-answered: ~110 (across 11 branches)
- Questions asked to user: 8 (fidelity, scope, nav, theme, triage-layout x2 clarified, write-paths, noise-filter) + design-source pivot to real HTML
- Branches explored: 11
- Conflicts detected: 1 design-vs-reality tension (hollow widgets) — resolved by user (build-honest case-by-case)

## Convergence
`converged` after 3 passes. Instability: Pass2=7 → Pass3=1 → 0.
- Pass 2: 7 material fixes (triage `created_at` migration + ADR0047; `app.py`→`main.py`; `ItemOrigin.MANUAL`; growth_velocity scalar; efficiency_peak float; errors-24h out-of-scope; removed no-op Knowledge drop-tabs).
- Pass 3: fixed migration-number collision (real head is `006`; triage migration renumbered `007`/down_revision `006`) consistently; CONVERGED.
- See `2026-06-08-mission-control-ui-redesign-convergence.csv`.

Convergence (instability score by pass):  7 ▇▇▇▇▇▇▇ → 1 ▇ → 0  (PNG renderer not invoked; ASCII sparkline shown)

## Key Decisions (summary; full log in -decisions.md)
- Theme: raw-hex two-orange (#ff6a2b CTAs + #ffb59a text/icons) + corrected Material surface ladder under shadcn vars; dark default + light + system/auto toggle.
- Fonts: self-host offline via @fontsource-variable (Space Grotesk / Hanken Grotesk / JetBrains Mono); `<Mono>` for all data.
- Shell: 64px lucide icon rail (2px orange active bar, Radix tooltips) + top app bar + cmdk ⌘K palette backed by new `GET /api/search` (ILIKE, grouped, facts degraded under Noop).
- Honest backend: `metrics` block + `GET /api/stats/timeseries`; "uptime"→ingestion success rate; avg triage time from `triage_cards`; `GET /api/topology` (2D SVG); `POST /api/actions`; `POST /api/memory/facts` (manual origin); `triage_cards.created_at` (migration 007); per-source relevance/noise thresholds + hot-reload.
- Pages: Overview (merge variants + hero region), Triage (A-shell + B-cards, ADR0027 preserved), Action Items (grouped + FAB), Sources (card grid + config drawer), Ingestion (ops + live log), Knowledge/Messenger/Settings.
- Dropped (no honest data): active_sessions, unread pings, blocked tasks, Settings kernel/arch/memory/network-latency, fabricated 99.98% uptime, mockup integrations (Jira/Slack/PagerDuty/Linear), "Deploy" button.
- Accessibility contrast contract: orange small-text AA on base surfaces only; near-black on orange fills; on-surface/peach text on elevated surfaces.

## ADRs produced (0033–0047)
0033 theme-token-architecture · 0034 theme-default-system · 0035 self-host-fonts-offline ·
0036 icon-rail-nav + app-shell-grid · 0037 server-side-global-search · 0038 chart-theme-module ·
0039 derived-metrics-endpoint · 0040 ingestion-success-rate-not-uptime · 0041 2d-svg-topology ·
0042 work-mode-client-only · 0043 triage-three-column · 0044 per-source-relevance-thresholds ·
0045 manual-fact-distinct-origin · 0046 contrast-contract-orange-on-dark · 0047 triage-cards.created_at-migration.

## Artifacts Produced
- Spec: docs/auto-plan/specs/2026-06-08-mission-control-ui-redesign-design.md
- Plan: docs/auto-plan/plans/2026-06-08-mission-control-ui-redesign.md (32 TDD tasks, 6 rollout phases)
- Decision log: docs/auto-plan/reports/2026-06-08-mission-control-ui-redesign-decisions.md
- ADRs: docs/adr/0033–0047
- State: ...-state.json · Convergence: ...-convergence.csv · Design ref: ~/workspace/workbench-stitch-designs/DESIGN-REFERENCE.md

## Preference Updates
- preference-workbench-ui-redesign (memory) — direction + finalized scope decisions.

## Notes / future (out of scope)
- Item-detail route for search hits; backend notification suppression for Work Mode; standalone neo4j topology node; visual-regression testing; true Errors-24h aggregate (proxy used).
