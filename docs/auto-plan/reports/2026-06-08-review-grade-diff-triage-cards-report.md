# Planning Report: Review-Grade Diff Triage Cards

## Execution Stats
- Mode: `--harden` (full run + hardening meta-loop)
- Sub-agents spawned: 12 (6 grillers, 1 spec writer, 1 spec reviewer, 1 plan writer, 1 plan reviewer, 1 final reviewer, 1 convergence judge)
- Grilling iterations: 1 (high convergence, no re-grill needed)
- Hardening passes: 3 (converged)
- Questions asked to user: 4 (during brainstorming) — content structure, delivery mechanism, scope, UI view
- Questions auto-answered by grillers: 46 decisions
- Branches explored: 6 (clustered from 9)
- Conflicts detected/resolved: 3 (content-gen location, hunk-bounding ownership, threaded-hunk ownership)
- Deferred-to-implementation: 2 (`meta phabricator.diff get` JSON schema → plan Task 8 verification gate; per-file Phabricator anchors → out of scope)

## Convergence
Status: **converged** after 3 passes.

```
instability  4 ┤█
             3 ┤█
             2 ┤█
             1 ┤█   █
             0 ┤█   █   █
               └pass1 pass2 pass3
```
- Pass 1 (baseline): ADR renumber 0022–0029 (concurrent `0021-stable-source-id` collision), spec↔plan path reconciliation (meta `workbench_meta/providers/...`, `gchat.py`), ADR-reference fixes. instability 4.
- Pass 2: plan `CompositeCardPresenter` now emits all 3 spec log events (`presenter_fallback`/`presenter_content_invalid`/`presenter_failure`) + test; stale-note removal. instability 1.
- Pass 3: confirming pass, zero material edits. instability 0 → CONVERGED.

CSV: `2026-06-08-review-grade-diff-triage-cards-convergence.csv`.

## Key Decisions (summary; full log in state.json, 46 entries)
1. Source-pluggable **CardPresenter** layer (`CompositeCardPresenter` routes by `source_type`, default `PlainCardPresenter`), built from a `presentation.providers` config list — mirrors `CompositeEnricher`.
2. Rich content stored as **typed-pydantic-in-dict** under `card_content['sections']` + `content_schema="diff.v1"` — no Alembic migration (ADR 0022).
3. **Presenter renders chat server-side** (cardsV2 + threaded hunks); UI renders client-side from JSON (ADR 0023).
4. Diff code fetched **lazily in the Diff Enricher** (deep mode), never in `poll()` or `raw_text` (ADR 0024).
5. Per-source **CardContentGenerator** registry; diff generator = single Opus 4.8 `json_schema` call, 5 sections, reuses existing memory context (ADR 0025).
6. **CardMessage** structured messenger interface + base `render_to_text` fallback; `GoogleChatMessenger` translates to cardsV2 (ADR 0026).
7. Triage interaction stays **numbered text replies**; cardsV2 buttons are display/links only — no event ingress (ADR 0027).
8. **CSS-only** curated-hunk rendering in the UI; no syntax/diff library (ADR 0028).
9. Presentation config **restart-only** in v1 (ADR 0029).

## Branch Tree
```
Review-Grade Diff Triage Cards (6 branches)
├── b1 Card Presenter abstraction + data model        [grilled, resolved]
├── b2 Phabricator diff fetch + Diff Enricher          [grilled, resolved]
├── b3 LLM card content generation                     [grilled, resolved]
├── b4 Google Chat cardsV2 + threading + messenger     [grilled, resolved]
├── b5 Backend API + UI detail view                    [grilled, resolved]
└── b6 Presentation config + per-source UX + x-cutting [grilled, resolved]
```

## Artifacts Produced
- Spec: `docs/auto-plan/specs/2026-06-08-review-grade-diff-triage-cards-design.md` (PASS)
- Plan: `docs/auto-plan/plans/2026-06-08-review-grade-diff-triage-cards.md` (PASS, 18 TDD tasks)
- ADRs: `docs/adr/0022`–`0029` (8 files)
- State: `docs/auto-plan/reports/2026-06-08-review-grade-diff-triage-cards-state.json`
- Convergence CSV + snapshots (`snapshots/pass-1`, `snapshots/pass-2`)
- Preference memory saved for diff triage-card structure

## Open Items for Implementation
- Plan Task 8 gates the diff parser on confirming the exact `meta phabricator.diff get` JSON schema in the cert-equipped container.
- Reuse-on-rescore keyed by `revision_id`: the `revision_id` is stored on the card; if the engine's rescore path is absent, follow-up wiring is recommended (noted in the plan).
- CONTEXT.md glossary additions + memory-caps drift fix are plan Task 18 (applied during implementation).
