# ADR 0053: Hard cutover, `models` → `domain` rename, and cross-repo coordination

**Status:** Proposed
**Date:** 2026-06-09

## Context
The reorg moves modules that form a de-facto public surface: `workbench.models` (50 internal + 12 cross-repo symbols), the `workbench.main:app` entrypoint, and `workbench.memory.*` (referenced by YAML `class:` paths). The owner chose a hard cutover with no back-compat shims, accepting cross-repo coordination and a one-line edit to existing local `config.yml` files.

## Decision
1. **Rename `workbench.models` → `workbench.domain`** as a package, split by concern, with `domain/__init__.py` re-exporting the full surface (a package facade — the permanent interface — **not** a shim; no `workbench.models` remains).
2. **Single atomic commit** in `workbench` (via `git mv`) updating all three reference classes in one shot: static imports, dynamic YAML `class:` paths, and **string-literal class paths inside Python** (`api/messenger.py`, `api/sources.py`, `config.py`) — the last being invisible to AST refactor tools and the primary silent-break risk.
3. **One-way ordering:** land `workbench` first, then a `workbench-meta` PR rewrites the 12 `domain` imports and re-pins `workbench`. `workbench-meta` → `workbench` is the only dependency direction.
4. **Verification gate** before finalizing: grep for string-literal paths, `ruff` + import smoke test, an `importlib` walk of every `config.example.yml` `class:` value, full `pytest`, and `make up` boot on `workbench.runtime.app:app`.

## Alternatives
- **Keep `workbench.models` / provide compat shims** — rejected by the owner (no shims; do it now).
- **`workbench-meta` merges first** — impossible: it depends on `workbench`, not vice versa.
- **Stage the move across commits** — rejected: leaves the tree red between commits.

## Consequences
Existing gitignored `config.yml` files need a one-line memory-path edit on pull (documented in the PR/CHANGELOG). The cross-repo break, if mis-sequenced, fails loudly (missing module) rather than silently. Provider `class:` paths are intentionally **not** moved, so the cross-repo surface change is limited to the 12 `domain` symbols.
