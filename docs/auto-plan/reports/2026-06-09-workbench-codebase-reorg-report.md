# Planning Report: workbench-codebase-reorg

**Date:** 2026-06-09 · **Mode:** `--harden` · **Domains:** backend, architecture, devops
**Convergence:** ✅ `converged` after 3 passes (instability 0 → 2 → 0)

## Execution Stats
- Sub-agents spawned: 6 (4 grillers, 2 hardening passes — pass 3 doubling as the convergence check)
- Grilling iterations: 1 (4 parallel branches)
- Hardening passes: 3 (pass 1 baseline, pass 2 found 2 gaps, pass 3 converged)
- Questions auto-answered (by grillers): ~40 across 4 branches
- Questions asked to user: 6 (2 batches: 4 initial scoping + 2 bubble-up)
- Branches explored: 8
- Conflicts detected: 2 (models naming A↔B; plugboard location A↔D) — both resolved by user decision

## Decision Log
| # | Question | Answer | Conf | Source |
|---|----------|--------|------|--------|
| D1 | Scope | Aggressive (layered pkgs, split models, regroup) | — | user |
| D2 | Import paths | Move & update everything, no shims, hard cutover | — | user |
| D3 | Folder doc | README.md per package | — | user |
| D4 | Enforcement | CLAUDE.md rule + pytest README guard | — | user |
| D5 | Plugboard home | providers/llm/plugboard.py | — | user |
| d001 | Taxonomy | domain/ config/ runtime/ telemetry/ providers/ pipeline/ storage/ api/ mcp/ migrations/ | high | griller-A |
| d002 | models.py | → workbench.domain package (split, __all__) | high | user+griller-B |
| d004 | memory | → workbench.providers.memory.* | high | glossary |
| d008 | registry | → providers/registry.py | high | glossary |
| d009 | web wiring | runtime/ pkg; main:app → runtime.app:app | medium | user+griller-A |
| d010 | config | config/ pkg; load_config path preserved | high | griller-A |
| d014 | cutover | single atomic commit; meta follows | high | griller-C |
| d015 | reference classes | static + YAML class: + string-literal paths | high | griller-C |
| d016 | two CONTEXT.md | make root authoritative; repoint test | medium | orchestrator |

## Hardening Passes
| Pass | Material? | Gaps Filled | Verdict | Snapshot |
|------|-----------|-------------|---------|----------|
| 1 | baseline | — | BASELINE (Snapshot-0) | `snapshots/pass-1/` |
| 2 | yes (2) | runtime/__init__.py; bare-import grep | NOT CONVERGED | `snapshots/pass-2/` |
| 3 | no (0) | — | CONVERGED | — |

Convergence (instability score per pass):
```
2 |        *
1 |
0 | *           *
  +--1----2----3--
```
_(PNG renderer skipped; CSV at `2026-06-09-workbench-codebase-reorg-convergence.csv`.)_

## Branch Tree
```
Reorg skeleton (8 branches)
├── b001 target package taxonomy        [griller-A]  → domain/config/runtime/telemetry/providers/...
│   ├── b006 runtime + main:app move     [user D8]
│   └── b007 telemetry grouping          [griller-A/D]
├── b002 models.py split + domain rename [user+griller-B]
├── b003 import-path migration + cross-repo [griller-C]
├── b004 providers cleanup + README + guard [griller-D / user D3,D4,D5]
├── b005 memory unification under providers [glossary]
└── b008 two-CONTEXT.md consolidation    [orchestrator]
```

## Notable findings surfaced during planning
- Cross-repo `workbench-meta` surface is **12 domain symbols**, not the 7 first assumed (diff-presenter + gchat pull 5 extra).
- Provider `class:` paths are **string literals** in `api/messenger.py`, `api/sources.py`, `config.py` — invisible to AST refactor tools (the top silent-break risk).
- `src/memory/` is a **separate service package** (`memory-service`), distinct from `workbench.memory.*` — out of scope.
- Provider interface subfolder names are **glossary-pinned** (renaming would contradict CONTEXT.md's "Provider" term) — so "move everything" is realized via domain rename, memory unification, registry/plugboard relocation, main move, and 4 new packages.
- Two `CONTEXT.md` files exist (root 239 / docs 205 lines); the test guards the smaller one — flagged for consolidation.

## Artifacts Produced
- Spec: `docs/auto-plan/specs/2026-06-09-workbench-codebase-reorg-design.md`
- ADRs: `docs/adr/0052-layered-package-taxonomy.md`, `0053-hard-cutover-domain-rename-and-cross-repo-protocol.md`, `0054-per-package-readme-convention.md`
- Plan: `docs/auto-plan/plans/2026-06-09-workbench-codebase-reorg.md`
- State: `docs/auto-plan/reports/2026-06-09-workbench-codebase-reorg-state.json`
- Convergence CSV + snapshots (`pass-1/`, `pass-2/`)
