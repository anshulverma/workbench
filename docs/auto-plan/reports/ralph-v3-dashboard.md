# Ralph Progress — v3 Dashboard Design Upgrade (master T275571165)

One subtask per iteration. Pick the lowest-numbered incomplete subtask whose deps are complete.
Read the full plan at `docs/auto-plan/plans/2026-06-11-v3-dashboard-design-upgrade.md` for each slice's detailed spec (file lists, acceptance criteria, test requirements).
Read the design prototype files at `/tmp/design_v3/workbench/project/app/` for visual reference.

| Subtask | Slice | Deps | Status | Notes |
|---------|-------|------|--------|-------|
| S1 T275571224 client foundation types + constants + helpers | 1 | — | TODO | |
| S2 T275571242 server foundation domain + migration 009 + storage | 2 | — | TODO | |
| S3 T275571262 server API endpoints | 3 | S2 | TODO | |
| S4 T275571286 shared UI primitives | 4 | S1 | TODO | |
| S5 T275571313 feedback store + hook | 5 | S1,S3 | TODO | |
| S7 T275571257 shell changes (nav, breadcrumbs, hover-expand) | 7 | S4 | TODO | |
| S6 T275571237 funnel core (FunnelStage, ItemFunnelDialog, MultiLineChart) | 6 | S1,S4,S5 | TODO | |
| S8 T275571278 settings sub-tabs | 8 | S4,S7 | TODO | |
| S9 T275571301 action items changes | 9 | S5,S6 | TODO | |
| S10 T275571322 triage changes | 10 | S6,S4 | TODO | |
| S11 T275571279 ingestion + LiveTail | 11 | S6,S10,S7 | TODO | |
| S12 T275571308 ingestion funnel page (filters) | 12 | S4,S5,S6,S10 | TODO | |
| S13 T275571331 search page | 13 | S4,S6,S12 | TODO | |
| S14 T275571351 overview + SourceFlow Sankey | 14 | S1,S4,S6 | TODO | |
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
