# Planning Report: item-lineage-identity

## Execution Stats
- Mode: `--harden --max-passes 10` (spec-file input)
- Sub-agents spawned: 9 (1 plan writer, 1 plan reviewer, 1 plan-fix writer, 3 hardening-pass agents, 2 convergence judges, 1 plan-edit applier ×2 ≈ counted in writers)
- Hardening passes: 4 (pass 1 baseline + passes 2–3 substantive + pass 4 fixed-point confirmation)
- Convergence: **converged** after 4 passes (instability 0)
- Questions auto-answered: all (design already grilled interactively before this run)
- Questions asked to user (bubble-up): 0
- Branches explored: 7 (1 discovered during hardening: change-detection/archival safety)
- Conflicts detected: 0

## Decision Log
| # | Question | Answer | Confidence | Source |
|---|----------|--------|------------|--------|
| d1 | ID representation | Materialized `path TEXT` + per-parent `seq SMALLINT`, integer surrogate PK kept | high | user + ADR 0062 |
| d2 | Tree shape & key | 3-tier (root/extracted/actions), arbitrary depth; root+descendants share adapter **stable** `source_id`; root = `parent_item_id IS NULL` row | high | user + code (pass 2–3) |
| d3 | Birth + LLM + archival | Root born at `enqueue` (INGESTED) with `{raw_text,source_type,id}` snapshot; re-resolved root-only via `get_item_by_source_id`; `LLMCallContext.item_paths` → `LlmCallRecord.items`; disappearance-archival safe via shared stable id | high | user + code |
| d4 | Immutability | Seqs append-only, never renumbered; `path` immutable after insert | high | user |
| d5 | Migration | `014_item_lineage`, `down_revision="013"`; tests run `alembic upgrade head` | high | code |
| d6 | Seq concurrency | `pg_advisory_xact_lock(parent.id)` + retry | high | best-practice + review |
| d7 | Granularity/depth | 1 source → 1 root, all derived nest; depth unbounded | high | user |

## Hardening Passes
Convergence: **converged** after 4 passes.

| Pass | Material? | Gaps Filled | Bubbled Up | Verdict Rationale | Snapshot |
|------|-----------|-------------|------------|-------------------|----------|
| 1 | baseline | — | 0 | baseline (spec corrected: migration 014/013, item_paths, alembic schema; ADR 0062; 15-task plan; 6 plan-review issues fixed incl. ABC-instantiation ordering) | pruned |
| 2 | yes | root-only `get_item_by_source_id`; root source snapshot; LIKE prefix-guard; feed isolation; migration ref fix | 0 | critical: source-key sharing made the resolver return a child, corrupting change-detection | `snapshots/pass-2/` |
| 3 | yes | archival safety verified + regression test; root `raw_data` shape verified all sources | 0 | both open gaps closed via code verification | `snapshots/pass-3/` |
| 4 | no | — | 0 | zero material edits — fixed point confirmed | `snapshots/pass-3/` (current==pass-3) |

Convergence (instability score = material + gaps + pending + unresolved):

```
pass:  1    2    3    4
score: 0 ▁  12 █  5 ▄  0 ▁
```

(CSV: `2026-06-18-item-lineage-identity-convergence.csv`; PNG best-effort alongside.)

## Branch Tree
```
item-lineage-identity (7 branches)
├── b1 identity representation .......... [user + ADR 0062]  resolved
├── b2 tree shape & lifecycle ........... [user + code]      resolved
├── b3 birth at ingestion & LLM linkage . [user + code]      resolved
├── b4 data model & constraints ......... [user]             resolved
├── b5 API & UI ......................... [user]             resolved
├── b6 migration & testing .............. [code]             resolved
└── b7 change-detection / archival safety  [discovered p2-3] resolved
```

## Artifacts Produced
- Spec: `docs/auto-plan/specs/2026-06-18-item-lineage-identity-design.md`
- Spec (original brainstorm copy): `docs/superpowers/specs/2026-06-18-item-lineage-identity-design.md`
- ADR: `docs/adr/0062-item-lineage-materialized-path.md`
- Plan (15 tasks, TDD): `docs/auto-plan/plans/2026-06-18-item-lineage-identity.md`
- State: `docs/auto-plan/reports/2026-06-18-item-lineage-identity-state.json`
- Convergence CSV/PNG, this report, tree.dot

## Key Hardening Outcomes (what the passes actually caught)
1. **Migration drift** — spec said latest=011/new=012; reality latest=013, so new migration is **014** (`down_revision="013"`).
2. **ABC-instantiation ordering** — adding all 5 abstract methods before implementing them would make `PgItemStore` non-instantiable and break the test fixture; split ABC+impl per task.
3. **Critical resolver bug** — root and children share `(source_type, source_id)`, so `get_item_by_source_id` must filter `parent_item_id IS NULL` or it returns a child and corrupts scheduler change-detection.
4. **Root source snapshot** — root must carry `{raw_text,...}` so `_parse_raw` change-detection works on re-poll.
5. **Archival safety** — roots/children are disappearance-archival-safe because they share the adapter **stable** `source_id` that populates `seen_ids`; covered by a new regression test.
6. **`LLMCallContext.item_paths`** — the context only had origin/purpose/stage; path-stamping needed a new field plumbed to `runtime/app.py`.
