# Planning Report: config-db-ui-authoritative

DB-authoritative config with `.env` bootstrap; `config.yml` removed; UI-authoritative
editing; all sections hot-apply. Run via `/auto-plan --harden --max-passes 10` on the
existing draft spec.

## Execution Stats
- Input mode: spec-file (hardened the existing draft)
- Sub-agents spawned: 8 (6 grillers, 2 hardening-pass agents — pass agents doubled as judges under the strict-bar convergence check)
- Grilling iterations: 1 (6 parallel branches)
- Hardening passes: 4 (1 baseline + 3 hardening); **converged at pass 4**
- Questions auto-answered: ~55
- Questions bubbled up to user: 2 (both answered)
- Branches explored: 10 (+3 discovered: workbench-meta seed, connection reverse-index, pipeline live-mutation)
- Conflicts detected: 3 ADR conflicts (0005, 0013, 0029) + 1 amendment (0017), all reconciled in ADR 0055

## Convergence

`Convergence: converged after 4 passes` (max 10).

Instability score by pass (material_changes + open_gaps + pending + unresolved):

```
pass:  1    2    3    4
inst:  0    2    1    0
       ·    █    ▄    ·      (2 → 1 → 0)
```

| Pass | Material? | Gaps Filled | Bubbled Up | Verdict | Snapshot |
|------|-----------|-------------|-----------|---------|----------|
| 1 | baseline | full artifact build (Snapshot-0) | 2 (answered) | baseline | — |
| 2 | yes (2) | entrypoint `BootstrapConfig` binding; redaction-vs-env-ref; connections via `/api/settings/connections`; explicit `extra=ignore`; `useSettings` re-point | 0 | NOT CONVERGED | `snapshots/pass-2/` |
| 3 | yes (1) | `llm` required-no-default hard-fail (no stub provider) | 0 | NOT CONVERGED | `snapshots/pass-3/` |
| 4 | no | — (all code refs verified) | 0 | CONVERGED | — |

_(No PNG renderer found; ASCII sparkline embedded above. CSV at
`2026-06-15-config-db-ui-authoritative-convergence.csv`.)_

## Key Decisions (highlights)
| # | Question | Answer | Source |
|---|----------|--------|--------|
| D1–D9 | core architecture | DB-authoritative; `.env` bootstrap; sparse JSONB doc; all-sections hot-apply; full UI; env-ref secrets | user (brainstorming) |
| BU-1 | workbench-meta override | generic seed seam `WORKBENCH_CONFIG_SEED`; meta migration separate | user bubble-up |
| BU-2 | new-secret flow | re-read `.env` on PATCH so new vars resolve live | user bubble-up |
| G-1 | auth_token rotation | none exists → token is `.env`-only | griller (code) |
| G-2 | `/api/config` fate | remove public route (no consumer); keep `/api/debug/config` | griller (code) |
| G-3 | config capture | engine/scheduler/worker capture at construction → live mutators + `scheduler.config` rebind | griller (code) |
| H2-1 | entrypoint boot | `__main__`/`cli_main` bind uvicorn from `BootstrapConfig` (not `load_config`) | harden pass 2 |
| H2-2 | secret disclosure | value `[REDACTED]` in GET body; env_var name via `{env_var, resolvable}` map | harden pass 2 |
| H3-1 | missing `llm` | required-no-default → hard-fail with clear message | harden pass 3 |

## Branch Tree
```
config-db-ui-authoritative (10 branches)
├── b01 Tier classification (.env vs DB)            [user + griller]
├── b02 Storage (app_settings JSONB, source_configs) [griller]
├── b03 Config assembly pipeline                     [griller]
├── b04 One-time import + seed seam                  [griller + user bubble-up]
├── b05 Hot-apply (worker/scheduler/engine/conn)     [griller — riskiest]
│   ├── connection→dependents reverse index          [discovered]
│   └── pipeline live-mutation setters               [discovered]
├── b06 Secrets & redaction                          [griller + user bubble-up]
├── b07 API surface + auth_token + /api/config       [griller]
├── b08 Settings UI                                  [griller]
├── b09 Decision reconciliation + docs               [griller]
│   └── workbench-meta seed seam                      [discovered]
└── b10 Testing & rollout                            [griller]
    ├── (H2) entrypoint boot-break                    [harden]
    └── (H3) llm required hard-fail                   [harden]
```

## Preference Updates
- `feedback_config_write_back.md` rewritten — reverses prior YAML-as-truth to DB-authoritative + `.env`; MEMORY.md index updated.

## Artifacts Produced
- Spec (hardened): `docs/auto-plan/specs/2026-06-15-config-db-ui-authoritative-design.md`
- ADR: `docs/adr/0055-db-authoritative-config-with-env-bootstrap.md`
- Plan (6 vertical slices): `docs/auto-plan/plans/2026-06-15-config-db-ui-authoritative.md`
- State: `docs/auto-plan/reports/2026-06-15-config-db-ui-authoritative-state.json`
- Convergence CSV: `docs/auto-plan/reports/2026-06-15-config-db-ui-authoritative-convergence.csv`
- Snapshots: `docs/auto-plan/reports/snapshots/pass-2/`, `pass-3/`
- Original draft (superseded): `docs/superpowers/specs/2026-06-15-config-db-ui-authoritative-design.md`
