# ADR 0054: Per-package README convention enforced by a test guard

**Status:** Proposed
**Date:** 2026-06-09

## Context
The rationale for what belongs in each directory was uncaptured, so contributors (human or agent) re-derive or violate it. The owner wants a small per-folder description file, kept honest automatically.

## Decision
Every directory under `src/workbench/` that contains an `__init__.py` carries a `README.md` (purpose; what belongs; what does not; "update when adding a new KIND of code"). `tests/test_folder_docs.py` walks the tree, parametrizes over packages, and asserts each has a non-empty `README.md`. Exclusions: `__pycache__` and `migrations/versions/` (Alembic-generated). The rule is mechanical and auto-discovering: a future package without a README fails CI. A CLAUDE.md "Project Structure" note states the convention for contributors.

## Alternatives
- **`ABOUT.txt` / `CONTEXT.md` per folder** — rejected: `README.md` renders in tooling and is conventional; per-folder `CONTEXT.md` would collide with the domain glossary.
- **Documentation only, no test** — rejected: drifts without enforcement.
- **Content-freshness check (assert every module is listed)** — rejected as brittle/high-maintenance; existence + non-empty is the durable floor.

## Consequences
Adding a new package now requires a README or CI fails — a deliberate, low-cost speed bump that keeps the tree self-describing. The guard verifies presence, not content accuracy; freshness relies on the CLAUDE.md convention and review.
