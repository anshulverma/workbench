# Ralph Progress — v3 Dashboard Design Upgrade (master T275571165)

One subtask per iteration. Pick the lowest-numbered incomplete subtask whose deps are complete.
Read the full plan at `docs/auto-plan/plans/2026-06-11-v3-dashboard-design-upgrade.md` for each slice's detailed spec (file lists, acceptance criteria, test requirements).
Read the design prototype files at `/tmp/design_v3/workbench/project/app/` for visual reference.

| Subtask | Slice | Deps | Status | Notes |
|---------|-------|------|--------|-------|
| S1 T275571224 client foundation types + constants + helpers | 1 | — | DONE | 21 tests pass; 3 type modules, funnel-constants, funnel-helpers, TriageTheme |
| S2 T275571242 server foundation domain + migration 009 + storage | 2 | — | DONE | 596 tests pass; 6 new files, 11 modified; migration 009 verified |
| S3 T275571262 server API endpoints | 3 | S2 | DONE | 620 tests; 4 new routers, 27 new test cases |
| S4 T275571286 shared UI primitives | 4 | S1 | DONE | 292 vitest; 9 components, 56 new tests |
| S5 T275571313 feedback store + hook | 5 | S1,S3 | DONE | 318 vitest; feedback-store.ts + useFeedback.ts, 26 new tests |
| S7 T275571257 shell changes (nav, breadcrumbs, hover-expand) | 7 | S4 | DONE | 328 vitest; nav 7 items, hover-expand, breadcrumbs, wb-icon.svg |
| S6 T275571237 funnel core (FunnelStage, ItemFunnelDialog, MultiLineChart) | 6 | S1,S4,S5 | DONE | 49 new tests; 4 components + smoothPath helper |
| S8 T275571278 settings sub-tabs | 8 | S4,S7 | DONE | 389 vitest; tab container + SettingsSystem extraction |
| S9 T275571301 action items changes | 9 | S5,S6 | DONE | 385 vitest; removed Work Mode, added throughput+filter tuning |
| S10 T275571322 triage changes | 10 | S6,S4 | DONE | 389 vitest; est badges, themes, card click, throughput chart |
| S11 T275571279 ingestion + LiveTail | 11 | S6,S10,S7 | DONE | 398 vitest; LiveTail component, page restructured |
| S12 T275571308 ingestion funnel page (filters) | 12 | S4,S5,S6,S10 | DONE | 411 vitest; 9 new files, interleaved funnel + dialogs |
| S13 T275571331 search page | 13 | S4,S6,S12 | DONE | 437 vitest; 9 new files, master/detail + 4 context renderers |
| S14 T275571351 overview + SourceFlow Sankey | 14 | S1,S4,S6 | DONE | 458 vitest; SourceFlow Sankey + clickable Hot Feed |
| S15 T275571367 MSW + a11y + test cleanup | 15 | all | TODO | |

## Rules
- Each iteration: implement ONE subtask end-to-end (code + tests)
- Run `cd ui && npx vitest run --reporter=verbose 2>&1 | tail -30` after each slice to verify tests pass
- For server slices: run `cd /home/anshulverma/workspace/workbench && python -m pytest tests/ -x -q 2>&1 | tail -20`
- Mark subtask DONE in this file + update the Meta Task status
- Commit after each completed slice with message: `feat(ui): slice N — <title>`
- If a test fails, fix it before moving on — do NOT skip
- Read the plan slice description carefully before starting — it has exact file paths, prop types, and acceptance criteria
- Reference the design prototype at `/tmp/design_v3/workbench/project/app/` for visual details (colors, layouts, interactions)

## Waves (parallelism guide)
- Wave 1: S1 + S2 (independent)
- Wave 2: S3 + S4
- Wave 3: S5 + S7
- Wave 4: S6 + S8
- Wave 5: S9 + S10
- Wave 6: S11 + S12 + S13 + S14
- Wave 7: S15

## Log
- iter 8: S8 DONE — Settings refactored to tab container (System/Sources/Messenger), SettingsSystem.tsx extracted, embedded prop on Sources+Messenger, 4 new routes in App.tsx. 389 tests.
- iter 7: S6 DONE — FunnelStage (correction picker+undo, timing, enricher badge), ItemFunnelDialog (treatment log+verdict+portal), MultiLineChart (Catmull-Rom+tooltip flip+HTML overlay), FilterTuningCard. smoothPath() added to funnel-helpers. 49 new tests.
- iter 6: S7 DONE — AppSidebar 7 items (removed Sources+Messenger, added Search@2), hover-expand (wb-rail-nav 64→216px), Breadcrumb in AppShell, TopBar route labels, wb-icon.svg, prefers-reduced-motion. 328 tests.
- iter 5: S5 DONE — feedback-store.ts (WBFeedback singleton, pub/sub, localStorage+fallback, cross-tab sync, refinedPrompt), useFeedback.ts (useFeedbackStore via useSyncExternalStore + TanStack Query hooks). 26 new tests, 318 total.
- iter 4: S4 DONE — 9 components (Portal, SectionHeader, ActionChip, ConfidenceBar, VerdictPill, StateDot, SourceChip, Breadcrumb, ui/tabs). 56 new tests, 292 total pass. Tabs uses HTML+ARIA (no Radix dep).
- iter 3: S3 DONE — 4 new routers (feedback 8ep, enrichers 3ep, loopbacks 2ep, funnel 5ep), filter_rules gains PATCH/DELETE, items gains search+snooze. 27 new tests, 620 total pass.
- iter 2: S2 DONE — domain/feedback.py (FeedbackCorrection, FilterTuningTask), enrichment.py gains EnricherConfig+LoopBackConfig, FilterRule+Item extended, migration 009 (pg_trgm, 6 tables, columns, GIN index), 5 new storage ABCs + PG impls (feedback/enrichers/loopbacks/funnel_traces/funnel_order), FilterRuleStore gains update/delete/reorder. 596 tests pass.
- iter 1: S1 DONE — 3 type modules (funnel.ts, feedback.ts, search.ts), funnel-constants.ts (ACTION_META/STAGE_META/SRC_ICON/SOURCE_COLORS/OUTPUT_COLORS), funnel-helpers.ts (ruleById/enricherStageFor/itemLog/stageDuration/stageTimings/buildFlowMatrix), TriageTheme in useTriage.ts. 21 tests pass. Fixed buildFlowMatrix bug (sources.map used tuple destructuring on objects).
