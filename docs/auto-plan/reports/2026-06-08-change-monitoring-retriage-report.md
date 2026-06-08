# Planning Report: Change Monitoring & Re-Triage

## Execution Stats
- Sub-agents spawned: 9 (3 grillers, 1 writer, 2 reviewers, 1 plan writer, 1 hardening pass, 1 convergence judge)
- Grilling iterations: 1
- Hardening passes: 2 (converged at pass 2)
- Questions auto-answered: 16
- Questions asked to user: 5
- Branches explored: 7 (2 known, 2 likely, 3 uncertain)
- Max depth reached: 2
- Conflicts detected: 1 (monitored_items table vs Item.raw_data — resolved in favor of Item.raw_data)

## Decision Log

| # | Question | Answer | Confidence | Source | Domain |
|---|----------|--------|------------|--------|--------|
| D1 | ChangeDetector interface shape | Sync, two dicts in, ChangeResult out | high | codebase pattern | backend |
| D2 | What counts as material? | Source-type-specific field sets, no LLM | high | user decision | pipeline |
| D3 | Where does old state come from? | Item.raw_data JSONB | high | codebase | backend |
| D4 | How to match old and new items? | Stable source_id (D12345, T67890) | high | user decision | pipeline |
| D5 | Separate cron job for monitoring? | No, single poll serves both | high | ADR 0014 | backend |
| D6 | No detector registered? | AlwaysMaterialDetector fallback | medium | principle | backend |
| D7 | Config shape? | change_detector per source in YAML | high | ADR 0005 | backend |
| D8 | SourceAdapter changes? | supports_monitoring() + stable_id() + poll_returns_complete_set() | high | codebase pattern | backend |
| D9 | Terminal detection? | Dual signal: explicit status + disappearance | high | codebase | pipeline |
| D10 | Card update vs new card? | Queued/sent: in-place. Responded/expired: new card | high | user decision | pipeline |
| D11 | Messenger update? | update_message(msg_id, text) -> bool, default False | high | codebase pattern | backend |
| D12 | Change-aware card copy? | ChangeContext model passed to generate_card() | high | principle | pipeline |
| D13 | Deferred cards? | Material change clears deferral via clear_deferral() | high | user decision | pipeline |
| D14 | Debounce strategy? | 2-min trailing-edge in-memory timer | medium | principle | backend |
| D15 | Daily cap interaction? | Re-triage counts, is_critical bypasses | high | principle | pipeline |
| D16 | New store methods? | get_item_by_source_id, get_active_by_source, update_raw_data, get_card_by_item_id, clear_deferral | high | codebase | backend |
| D17 | Race condition? | Re-read card status before update | medium | principle | backend |
| D18 | Terminal state? | Immediate archive, no cooldown | high | user decision | pipeline |
| D19 | Non-monitoring sources? | supports_monitoring() == False, skip re-check | high | principle | backend |
| D20 | Scale? | Single-user, ~50 items per source, no tiered cadence | high | user model | backend |
| D21 | Re-triage options? | LLM-generated from ChangeContext, contextual options | high | principle | pipeline |

## Hardening Passes

Convergence: **converged** after 2 passes.

| Pass | Material? | Gaps Filled | Questions Bubbled Up | Verdict Rationale | Snapshot |
|------|-----------|-------------|----------------------|-------------------|----------|
| 1 | baseline | — | 0 | Baseline artifacts from Phases 1-4 | `snapshots/pass-1/` |
| 2 | yes (4 material) | 4 | 1 (GitHub poll_returns_complete_set — auto-answered) | old_raw timing bug, false disappearance, missing expires_at, update_raw_data signature | `snapshots/pass-2/` |

Convergence check after pass 2: instability=0 (0 material changes, 0 gaps, 0 pending, 0 unresolved). **CONVERGED.**

## Branch Tree

```
Skeleton (7 branches)
├── ChangeDetector Interface Design (9 decisions) [uncertain → grilled]
│   ├── Card Update vs New Card Logic (discovered)
│   ├── ProcessedStore Interaction After Stable ID (discovered)
│   └── Adapter poll() Contract for Re-check (discovered)
├── Monitoring Lifecycle and Polling Strategy (10 decisions) [uncertain → grilled]
│   ├── ChangeDetector Contract and Materiality (discovered)
│   ├── Re-triage Card Content and UX (discovered)
│   ├── Adapter Extension Surface (discovered)
│   └── Monitoring Cleanup and Orphan Detection (discovered)
├── Triage Card Update and Re-triage Flow (7 decisions) [uncertain → grilled]
│   ├── Messenger Update API (discovered)
│   ├── Debounce Buffer Integration (discovered)
│   └── Re-triage Card Options (discovered)
├── Stable Source ID (settled by user) [known]
├── YAML Config Shape (settled by ADR pattern) [known]
├── Store Method Extensions (derived from design) [likely]
└── Daily Cap Interaction (derived from principle) [likely]
```

## Preference Updates

None — no new preferences saved during this planning session.

## Artifacts Produced

- `docs/auto-plan/specs/2026-06-08-change-monitoring-retriage-design.md` — design spec (~900 lines)
- `docs/auto-plan/plans/2026-06-08-change-monitoring-retriage.md` — 11-slice implementation plan
- `docs/adr/0021-stable-source-id-with-change-detection-routing.md` — ADR for stable IDs + change detection routing
- `docs/auto-plan/reports/2026-06-08-change-monitoring-retriage-report.md` — this report
- `docs/auto-plan/reports/snapshots/pass-1/` — pre-hardening snapshot
- `docs/auto-plan/reports/snapshots/pass-2/` — post-hardening snapshot (converged)
