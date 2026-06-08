# Planning Report: Makefile Developer Workflow (remove `workbench` console script)

**Date:** 2026-06-07 · **Domains:** devops, backend, api-design · **Branch:** feat/dashboard-followups

## Execution Stats
- Sub-agents spawned: 0 (inline fast path — all decisions settled in Phase 0.5; survey done directly)
- Grilling iterations: 0 (no uncertain branches after clarification)
- Questions asked to user: 5 (4 idea-clarification + 1 commit-strategy)
- Branches: 6 (Makefile target set, server launcher, triage script, console-script removal, UI build + image fix, workbench-meta lockstep)
- Conflicts detected: 0

## Decision Log
| # | Question | Answer | Source |
|---|----------|--------|--------|
| 1 | Terminal triage CLI | Keep as `scripts/triage.py` + `make triage` | user |
| 2 | Serve mechanism | `python -m workbench` thin launcher honoring `config.server.host` | user |
| 3 | Scope | Both repos in lockstep (workbench/ + workbench-meta/) | user |
| 4 | UI in `make build` | Yes — `ui-build` target + fix Dockerfile `/app/ui-dist`→`/app/ui/dist` | user |
| 5 | Lint/format tool | Add `ruff` (lint+format) | recommendation |
| 6 | Serve config/override flags | Drop flags; use `WORKBENCH_CONFIG[_OVERRIDE]` env | inferred (matches container+meta) |

## Key Findings
- `workbench serve` had no runtime callers (entrypoint.sh + meta override run uvicorn directly); only docs referenced it.
- `workbench triage` was used by `make triage` + console.py + ADR 0001.
- No tests import `workbench.cli` → clean removal.
- Latent bug: base `Dockerfile` copied UI to `/app/ui-dist` but `main.py` mounts `/app/ui/dist` → base image 404'd `/ui`. Fixed in the plan.
- Meta mounts host-built `ui/dist` as a volume + sets `WORKBENCH_CONFIG_OVERRIDE` env → override survives script removal; requires a host `ui-build` before `make up`.
- Extra host-binding launch paths unified: `scripts/workbench-start.sh` (was `--host 0.0.0.0`), meta override command (was `--host ::`).

## Branch Tree
```
Makefile workflow (6 branches, all user-resolved)
├── Base Makefile target set ............... [user]
├── Server launcher python -m workbench .... [user] → ADR 0020
├── Terminal triage scripts/triage.py ...... [user]
├── Remove workbench console script ........ [user] → ADR 0020
├── UI build + Dockerfile path fix ......... [user]
└── workbench-meta lockstep ................ [user]
```

## Artifacts Produced
- Spec: `docs/auto-plan/specs/2026-06-07-makefile-workflow-design.md` (cb9690d)
- ADR: `docs/adr/0020-make-as-dev-interface-no-console-script.md` (cab55d1)
- Plan: `docs/auto-plan/plans/2026-06-07-makefile-workflow.md` (c3c67fb) — 9 TDD tasks
- State: `docs/auto-plan/reports/2026-06-07-makefile-workflow-state.json`

## Notes / Follow-ups
- `--loop asyncio` (meta override) is dropped by `python -m workbench`; verify meta starts cleanly (uvicorn default loop) or thread it through the launcher.
- Task 9 lands in the separate workbench-meta repo.
