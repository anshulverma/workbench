# Implementation Plan: Workbench Codebase Reorganization

**Spec:** `docs/auto-plan/specs/2026-06-09-workbench-codebase-reorg-design.md`
**ADRs:** 0052, 0053, 0054
**Date:** 2026-06-09

## Strategy
A pure structural move with **no behavior change**. The final cutover lands as **one atomic commit** in `workbench` (ADR 0053). To keep the work reviewable, build it on a branch in the slice order below, running the full suite after each slice; squash/assemble into the atomic commit at the end (or land per-slice on the branch, then verify the whole before opening the cross-repo PR). `workbench-meta` is a **separate, follow-on PR**.

Use `git mv` for every relocation to preserve history. After each slice: `ruff check src/ tests/ && pytest`.

---

### Slice 0 — Baseline & guardrails (no moves yet)
1. Confirm clean tree, full suite green: `ruff check src/ tests/ && pytest`. Record the pass count.
2. Add `tests/test_folder_docs.py` (ADR 0054) **now**, but `xfail`/skip until READMEs land — or land it last (Slice 7). Decision: land it in Slice 7 so CI never goes red mid-branch.
3. Write a throwaway verification script `scripts/verify_class_paths.py`: walks `config.example.yml` `class:` values through `importlib.import_module`; greps `src/ config*.yml` for string-literal class paths (`'"workbench\.[a-z_.]+\.[A-Z]'`) and asserts each resolves. Used as the gate in Slice 8. (Keep or delete per taste.)

**Verify:** suite green; script runs against current tree with zero failures.

---

### Slice 1 — `domain/` package (was `models.py`) [highest churn]
1. `mkdir src/workbench/domain`; create submodules `enums.py, items.py, pipeline.py, triage.py, diff.py, filters.py, preferences.py, enrichment.py, sources.py, plans.py` per spec §5. Move classes by concern; `enums.py` is the dependency-free leaf; add `from __future__ import annotations` to each; declare `__all__` per submodule.
2. `domain/__init__.py` re-exports every public symbol; build aggregate `__all__`.
3. Delete `models.py`.
4. Rewrite all internal importers: `from workbench.models import X` → `from workbench.domain import X` (50 files; mechanical — `grep -rl "workbench.models" src tests`).
5. Add `tests/test_domain_surface.py` asserting the 12 cross-repo symbols resolve from `workbench.domain` (spec §5).
6. `domain/README.md` (submodule map).

**Verify:** `pytest`; `python -c "from workbench.domain import RawItem, DiffCardContent, ItemCategory"`.

---

### Slice 2 — `telemetry/` package
1. `git mv` `metrics.py, instrumentation.py, logging.py, usage_aggregator.py, alerting.py, privacy.py` → `telemetry/`; add `telemetry/__init__.py`.
2. Update importers (`grep -rl "workbench.\(metrics\|instrumentation\|logging\|usage_aggregator\|alerting\|privacy\)" src tests`).
3. `telemetry/README.md`.

**Verify:** `pytest`; confirm Prometheus + structlog setup still wires in `runtime/app.py` (next slice) — for now, importers compile.

---

### Slice 3 — `providers/` cleanup: plugboard, registry, memory
1. `git mv src/workbench/providers/_plugboard.py src/workbench/providers/llm/plugboard.py`; update its importers (`providers/llm/anthropic.py`, `providers/queue_scorer/llm.py`, `telemetry/usage_aggregator.py`, `runtime/app.py`).
2. `git mv src/workbench/registry.py src/workbench/providers/registry.py`; update importers (`grep -rl "workbench.registry" src tests` — 6 files incl. `api/sources.py` `source_id_for`).
3. `git mv src/workbench/memory/{base,http,noop}.py src/workbench/providers/memory/`; `git mv` the `memory/__init__.py`; update importers (`grep -rl "workbench.memory" src tests`).
4. README in `providers/`, `providers/memory/` (note: `doc_reader/` is a latent/unwired interface — say so in its README). Add per-interface READMEs in Slice 7.

**Verify:** `pytest`; `python -c "from workbench.providers.memory.noop import NoopMemoryLayer; from workbench.providers.llm.plugboard import record_plugboard_call; from workbench.providers.registry import create_provider"`.

---

### Slice 4 — `config/` package
1. `git mv config.py config/models.py` (split `load_config`/OmegaConf into `config/loader.py` if cleanly separable; otherwise keep loader in `config/loader.py` and config models in `config/models.py`).
2. `git mv config_writer.py config/writer.py`.
3. `config/__init__.py` re-exports `load_config` and the config models so `workbench.config.load_config` is preserved (cross-repo + internal).
4. Update importers of `workbench.config_writer` → `workbench.config.writer`. Note `config.py:125` enrichment-default string literal stays `workbench.providers.enrichment.stub.StubEnricher` (unchanged).
5. `config/README.md`.

**Verify:** `pytest`; `python -c "from workbench.config import load_config"`.

---

### Slice 5 — `runtime/` package + `main:app` move (ADR 0053 D8)
1. `git mv auth.py runtime/auth.py`, `git mv middleware.py runtime/middleware.py`. **Create `runtime/__init__.py`** (new package — required for `import workbench.runtime.app` to resolve and for `pyproject` `packages.find` to discover the package). Confirm the other new packages also have an `__init__.py`: `domain/` (Slice 1), `telemetry/` (Slice 2), `config/` (Slice 4).
2. `git mv main.py runtime/app.py`; ensure it exposes `app`. Update internal imports inside it to new paths (domain, telemetry, config, providers.registry, providers.memory).
3. Update `__main__.py` to import from `workbench.runtime.app`.
4. Update entrypoints/scripts: `entrypoint.sh`, `scripts/e2e-setup.sh`, `scripts/workbench-start.sh` → `uvicorn workbench.runtime.app:app`; `Dockerfile` if it names the module. **Leave** `docker-compose.yml` `memory.main:app` (memory-service).
5. `runtime/README.md`.

**Verify:** `pytest`; `python -c "import workbench.runtime.app"`; `python -m workbench --help` (or boot path); dry-run `entrypoint.sh` command.

---

### Slice 6 — `api/redaction.py`
1. `git mv redaction.py api/redaction.py`; update its 2 importers (`grep -rl "workbench.redaction"`).
2. `api/README.md` (route modules + Redaction Rule).

**Verify:** `pytest`.

---

### Slice 7 — READMEs everywhere + test guard + CLAUDE.md
1. Add `README.md` to every remaining `__init__.py`-bearing package: `pipeline/`, `storage/`, `storage/postgres/`, `mcp/`, `migrations/`, each `providers/<interface>/`, `providers/`. Use the spec §6 template.
2. Land `tests/test_folder_docs.py` (spec §6 algorithm; exclusions `__pycache__`, `migrations/versions`).
3. Update `CLAUDE.md` "Project Structure" block: new taxonomy + the README convention (D4 text).

**Verify:** `pytest tests/test_folder_docs.py` green (proves every package has a README).

---

### Slice 8 — Glossary + CONTEXT consolidation + config + final gate
1. Add the §8 glossary terms to root `CONTEXT.md` (Domain, Telemetry, Runtime, Package facade, Package README; plugboard clarification).
2. Consolidate CONTEXT (spec §9): repoint `tests/test_context_doc.py` to `../CONTEXT.md`; delete `docs/CONTEXT.md` (or one-line pointer).
3. Update `config.example.yml` memory `class:` paths → `workbench.providers.memory.{noop,http}.*`. Document the same one-line edit for local `config.yml` in the PR description / CHANGELOG.
4. **Verification gate (spec §7.4):** run `scripts/verify_class_paths.py`; `grep -rEn '"workbench\.[a-z_.]+\.[A-Z][A-Za-z]*"' src/ config*.yml` resolves; `ruff check`; full `pytest`; `make up` + `alembic upgrade head` boot.

**Verify:** all gate checks green.

---

### Slice 9 — `workbench-meta` follow-on PR (separate repo, after `workbench` lands)
1. `grep -rl "from workbench.models" workbench_meta tests` → rewrite to `from workbench.domain`.
2. Confirm no other moved symbol is imported (providers bases, pipeline builders, `config.load_config` are unchanged).
3. Re-pin/reinstall `workbench` (`pip install -e ../workbench`); run `pytest` in `workbench-meta`.

**Verify:** `workbench-meta` suite green against the reorganized `workbench`.

---

## Definition of done
- All slices' verifications green.
- `workbench` cutover assembled as the atomic commit (ADR 0053); `workbench-meta` PR green.
- `tests/test_folder_docs.py`, `tests/test_domain_surface.py`, `tests/test_context_doc.py` (repointed) all pass.
- `make up` boots on `workbench.runtime.app:app`; `importlib` walk of `config.example.yml` resolves every `class:`.
- No references to the 14 moved top-level names remain anywhere, in **either** import form. A single grep covering all 14 names AND both `workbench.X` (dotted) and `from workbench import X` (bare submodule) forms must return zero hits across `src/ tests/ scripts/ config*.yml` and `workbench-meta`:
  `grep -rEn 'workbench\.(models|metrics|memory|main|registry|redaction|auth|middleware|config_writer|alerting|privacy|instrumentation|logging|usage_aggregator)\b|from[[:space:]]+workbench[[:space:]]+import[[:space:]].*\b(models|metrics|memory|main|registry|redaction|auth|middleware|config_writer|alerting|privacy|instrumentation|logging|usage_aggregator)\b' src/ tests/ scripts/ config*.yml`
  (The `from workbench import X` form would otherwise fail loudly at import time, but the gate must prove zero, not rely on a runtime crash.)

## Rollback
Pure move; revert the atomic commit. `workbench-meta` PR is independent and revertible. No data/migration changes.
