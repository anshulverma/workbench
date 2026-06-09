# Design Spec: Workbench Codebase Reorganization

**Date:** 2026-06-09
**Status:** Proposed
**Domains:** backend, architecture, devops
**Related ADRs:** 0052 (layered taxonomy), 0053 (hard cutover + domain rename + cross-repo protocol), 0054 (per-package README convention). Touches the spirit of 0008 (src layout), 0049 (plugboard sink).

## 1. Problem

`src/workbench/` has accreted into a layout that no longer communicates intent:

1. **`providers/` is a partial junk drawer.** `providers/_plugboard.py` is transport-view LLM-gateway instrumentation, not a Provider (no base interface, no `ProviderConfig`, never resolved via `create_provider`). It sits at the package root next to legitimate interface subfolders.
2. **13 loose cross-cutting modules at the package root** (`metrics.py`, `instrumentation.py`, `logging.py`, `usage_aggregator.py`, `alerting.py`, `privacy.py`, `redaction.py`, `auth.py`, `middleware.py`, `config.py`, `config_writer.py`, `registry.py`, `models.py`) mix telemetry, web wiring, config, and the domain vocabulary with no grouping. Low locality: a telemetry change and a domain change look identical from the tree.
3. **`models.py` is a 434-line single file** holding 9 enums + 41 models — imported by 50 internal files and the external `workbench-meta` repo.
4. **`workbench.memory.*` is a top-level package** even though `MemoryLayer` is, per the glossary, a Provider — inconsistent with the other 8 provider interfaces under `providers/`.
5. **No per-folder documentation** — the rationale for what belongs in each directory is not captured anywhere, so the next contributor (human or agent) re-derives it or gets it wrong.

## 2. Goals / Non-goals

**Goals**
- A layered, self-describing package taxonomy where every module's location follows from a single placement rule.
- Each package folder carries a small `README.md` stating its purpose and what belongs there, kept honest by a CI test guard.
- A clean, **hard cutover** (no back-compat shims) that updates every reference — static imports, dynamic YAML `class:` paths, string-literal class paths, scripts, and the `workbench-meta` repo — leaving both repos green.

**Non-goals**
- No behavior changes. This is a pure structural move; every test that passed before passes after.
- `src/memory/` (the separate `memory-service` distribution, package `memory`, run as `memory.main:app`) is **out of scope** — it is a different package from `workbench.memory.*`.
- No changes to `pipeline/`, `storage/`, `mcp/` internal structure, or to `migrations/` (pinned by `alembic.ini script_location`).
- Provider **interface subfolder names** are not renamed (see §4.1).

## 3. Settled decisions (user-confirmed)

| # | Decision |
|---|----------|
| D1 | Scope = **aggressive**: layered packages, split `models.py`, regroup. |
| D2 | Import paths = **move and update everything**; **no back-compat shims**; hard cutover; update `config.example.yml`, local `config.yml`, string-literal allowlists, `workbench-meta` (lockstep), entrypoint/scripts. |
| D3 | Per-folder doc = **`README.md`** in every package folder. |
| D4 | Enforcement = CLAUDE.md rule + **pytest** asserting every package dir has a non-empty `README.md`. |
| D5 | Plugboard shim → **`providers/llm/plugboard.py`**. |
| D6 | Provider interface subfolder names are **glossary-pinned** and retained. |
| D7 | `workbench.memory.*` → **`workbench.providers.memory.*`** (MemoryLayer is a Provider). |
| D8 | `main.py` → **`runtime/app.py`**; `workbench.main:app` → `workbench.runtime.app:app`; entrypoint + scripts updated (no `main.py` shim). |

## 4. Target taxonomy

```
src/workbench/
  __init__.py            # __version__ (unchanged)
  __main__.py            # python -m workbench -> imports runtime.app (updated)
  domain/                # entity vocabulary: pydantic models + enums (was models.py)
  config/                # config models, loader (OmegaConf), writer (ruamel)
  runtime/               # ASGI app factory + app-level middleware + entrypoint
  telemetry/             # emitted operational signals: metrics, logging, instrumentation,
                         #   usage aggregation, alerting, log sanitizing processor
  providers/             # pluggable implementations behind base interfaces + the registry
    registry.py          #   Provider Registry (was workbench/registry.py)
    llm/                 #   + plugboard.py (was providers/_plugboard.py)
    source/ messenger/ queue_scorer/ enrichment/ connection/ change_detector/ doc_reader/
    memory/              #   MemoryLayer providers (was workbench/memory/)
  pipeline/              # orchestration stages (unchanged)
  storage/               # repositories + postgres/ (unchanged)
  api/                   # HTTP route modules + redaction.py (Redaction Rule)
  mcp/                   # MCP server (unchanged)
  migrations/            # alembic (unchanged; pinned by alembic.ini)
```

**Placement rule (decide by primary role, recorded in each README):**
1. Domain entity/enum → `domain/`
2. Pluggable impl behind a base interface → `providers/<interface>/`
3. Storage repository → `storage/`
4. Pipeline stage → `pipeline/`
5. HTTP route or API-output rule → `api/`
6. Config model/loader/writer → `config/`
7. Emitted operational signal (metric / log / instrumentation / usage / alert / log processor) → `telemetry/`
8. ASGI app assembly or app-level middleware → `runtime/`

No module lands at `src/workbench/` root except `__init__.py` and `__main__.py`.

### 4.1 Why provider subfolder names are retained
CONTEXT.md defines **Provider** as the canonical term and explicitly lists `llm`, `source`, `messenger`, `queue_scorer`, `enrichment`, `connection`, `change_detector`, `doc_reader` as the interface families. Renaming them (e.g. `llm` → `language_model`) would contradict the glossary and churn every `class:` path for zero semantic gain. The "move everything" mandate (D2) is therefore realized through: the `domain` rename, the `memory` unification, the `registry`/`plugboard` relocations, the `main:app` move, and the four new packages — **not** by renaming correct, glossary-pinned names.

### 4.2 Full module → target mapping

| Current | Target | Path change | Cross-repo? |
|---|---|---|---|
| `models.py` | `domain/{enums,items,pipeline,triage,diff,filters,preferences,enrichment,sources,plans}.py` + `domain/__init__.py` | `workbench.models` → `workbench.domain` | **yes** (12 symbols) |
| `config.py` | `config/models.py` + `config/loader.py` | `workbench.config.load_config` preserved via `config/__init__.py` | no |
| `config_writer.py` | `config/writer.py` | `workbench.config_writer` → `workbench.config.writer` | no |
| `registry.py` | `providers/registry.py` | `workbench.registry` → `workbench.providers.registry` | no |
| `metrics.py` | `telemetry/metrics.py` | yes | no |
| `instrumentation.py` | `telemetry/instrumentation.py` | yes | no |
| `logging.py` | `telemetry/logging.py` | yes | no |
| `usage_aggregator.py` | `telemetry/usage_aggregator.py` | yes | no |
| `alerting.py` | `telemetry/alerting.py` | yes | no |
| `privacy.py` | `telemetry/privacy.py` (Sanitizing Processor) | yes | no |
| `redaction.py` | `api/redaction.py` (Redaction Rule) | yes | no |
| `providers/_plugboard.py` | `providers/llm/plugboard.py` | de-underscore | no |
| `auth.py` | `runtime/auth.py` | yes | no |
| `middleware.py` | `runtime/middleware.py` | yes | no |
| `main.py` | `runtime/app.py` | `workbench.main:app` → `workbench.runtime.app:app` | no (scripts) |
| `memory/{base,http,noop}.py` | `providers/memory/{base,http,noop}.py` | `workbench.memory.*` → `workbench.providers.memory.*` | no (config only) |
| `api/*` | `api/*` (unchanged) + `redaction.py` added | none | no |
| `pipeline/*`, `storage/*`, `mcp/*`, `migrations/*`, provider interface subfolders | unchanged | none | no |

## 5. `domain/` package (split of `models.py`)

`workbench.models` → `workbench.domain`. The single file is split by domain concern; `domain/__init__.py` re-exports the full public surface (with `__all__`) so callers import `from workbench.domain import X` and never learn submodule locations. This `__init__` **is the package interface**, not a back-compat shim (there is no `workbench.models` left behind — every import site is rewritten).

| Submodule | Contents |
|---|---|
| `enums.py` | Priority, ItemStatus, ItemCategory, ItemOrigin, EntityType, ActionCategory, JobStatus, JobTrigger, QueueEntryStatus (dependency-free leaf) |
| `items.py` | RawItem, ExtractedItem, Item, ItemUpdate, ItemFilters |
| `pipeline.py` | PipelineJob, IngestionQueueEntry, IngestionRun |
| `triage.py` | TriageOption, TriageCard, TriageResponse, TriageResponseResult, CardLink, CardSection, ThreadHunk, CardMessage, ChangeContext |
| `diff.py` | DiffMetadata, DiffRisk, DiffHunkSection, DiffCardContent |
| `filters.py` | FilterRule |
| `preferences.py` | InteractionEntry, PreferenceSummary, Fact, EntityKnowledge, Relationship, SystemAction, UserTodo, InterpretedResponse |
| `enrichment.py` | EnrichmentTrace, TraceFilters, EnrichmentBudget |
| `sources.py` | SourceRelevanceConfig, SourceConfig, SourceConfigUpdate |
| `plans.py` | Plan, PlanFilters, PlanUpdate |

Rules: enums in a dependency-free leaf (`enums.py`) to prevent cycles; `from __future__ import annotations` in every submodule (cheap insurance for future cross-submodule refs); each submodule declares `__all__`, aggregated in `__init__.py`.

**Cross-repo contract (must stay importable from `workbench.domain`):** `RawItem, ExtractedItem, EnrichmentBudget, ChangeContext, CardMessage, CardSection, CardLink, ThreadHunk, TriageOption, TriageCard, DiffCardContent, ItemCategory` — **12 symbols** (the griller cross-check found 12, broader than the 7 first assumed; the diff-presenter and gchat messenger in `workbench-meta` pull the extra five). A `test_domain_surface.py` asserts each resolves from `workbench.domain`.

## 6. Per-package README convention (D3/D4)

**Template (kept small):**
```markdown
# <package path, e.g. providers/llm>

**Purpose:** one sentence.

**What belongs here:** ...

**What does NOT belong here:** ...

**Update this README when** you add a new KIND of code here
(a new interface family / a new top-level concern) — not for every new file.
```

**Which dirs get a README:** every directory under `src/workbench/` containing an `__init__.py` (i.e. an importable package), **except** `__pycache__` and `migrations/versions/` (Alembic-generated; its `__init__.py` is a 0-byte import anchor). `migrations/` itself gets one (hand-authored env). Sub-packages (`storage/postgres/`) get their own.

**Test guard (`tests/test_folder_docs.py`):** mirrors the existing `tests/test_context_doc.py` style (module-level path constant, plain asserts, no fixtures). Walks `src/workbench`, treats a dir as a package iff it contains `__init__.py`, parametrizes over discovered packages (one failure per missing dir), asserts `README.md` exists and `size > 0`. Exclusions: any segment `== "__pycache__"`, and `migrations/versions`. Auto-discovery means a future package without a README fails CI — the desired behavior.

**CLAUDE.md rule (D4):** add to "Project Structure": *"Every package directory under `src/workbench/` carries a `README.md` describing its purpose and placement rule. When you add a new kind of code to a folder (a new provider interface, a new cross-cutting concern), update that folder's `README.md`. `tests/test_folder_docs.py` enforces presence."*

## 7. Cross-repo hard cutover (D2)

### 7.1 Three reference classes (and the tool that catches each)
1. **Static Python imports** (`from workbench.x import ...`) — caught by `ruff`/grep; mechanically rewritable.
2. **Dynamic YAML `class:` paths** — only found by grepping `*.yml`/`*.yaml`. Invisible to Python tooling.
3. **String-literal class paths inside Python** — the silent-failure trap. Confirmed locations: `api/messenger.py` (messenger map), `api/sources.py` (`ADAPTER_ALLOWLIST`), `config.py:125` (enrichment default `"class": "workbench.providers.enrichment.stub.StubEnricher"`). A Python-AST refactor tool does **not** rewrite these. Grep: `grep -rEn '"workbench\.[a-z_.]+\.[A-Z][A-Za-z]*"' src/ config*.yml`.

### 7.2 Reference inventory to update
- **Static imports**: all `src/workbench/**/*.py` referencing moved modules (domain, config, registry, telemetry/*, runtime/*, providers.memory, providers.llm.plugboard); all `tests/**`.
- **String-literal paths**: `api/messenger.py`, `api/sources.py` (these reference `providers.messenger.*`/`providers.source.*` which **do not move** — verify they are unaffected), `config.py` enrichment default (unaffected — stub stays). The genuinely-changing string literals here are none for providers, but re-grep after the move to prove zero dangling.
- **YAML `class:` paths**: `config.example.yml` and per-developer `config.yml` — only the **memory** entry changes (`workbench.memory.noop.NoopMemoryLayer` → `workbench.providers.memory.noop.NoopMemoryLayer`, `workbench.memory.http.HttpMemoryLayer` → `workbench.providers.memory.http.HttpMemoryLayer`). Provider `class:` paths are unchanged (D6). `config.yml` is gitignored — document the one-line memory-path edit in the PR description / CHANGELOG so existing deployments fix it on pull.
- **Entrypoints/scripts** (`workbench.main:app` → `workbench.runtime.app:app`): `entrypoint.sh`, `scripts/e2e-setup.sh`, `scripts/workbench-start.sh`; `__main__.py`; `Dockerfile` if it names the module. `docker-compose.yml` `memory.main:app` is the **memory-service** — leave it.
- **Packaging**: `pyproject.toml` uses `packages.find where=["src"]` — auto-discovers new packages that contain `__init__.py`; no manual edit, but **every new package dir must have `__init__.py`**. Of the four new packages, `domain/`, `telemetry/`, and `config/` create their own `__init__.py` (facade/aggregation); `runtime/` has **no** file carrying an `__init__.py` moved into it (`main.py`/`auth.py`/`middleware.py` are leaf modules), so `runtime/__init__.py` **must be created explicitly** or `import workbench.runtime.app` and `packages.find` both fail. `providers/memory/` inherits its `__init__.py` from the moved `memory/__init__.py`.
- **`alembic.ini`**: `script_location=src/workbench/migrations` unchanged (migrations don't move).
- **`workbench-meta`** (separate repo, lockstep PR): rewrite `from workbench.models import ...` → `from workbench.domain import ...` (12 symbols across `diff_enricher`, `diff_generator`, `diff_presenter`, `gchat`, `meta_anthropic`, `meta_scorer`, adapters). Its `class:` configs reference `workbench_meta.*` (own) — unaffected. Its imports of `workbench.providers.*.base`, `workbench.pipeline.*`, `workbench.config.load_config` are **unchanged** by this reorg.
- **Docs**: `CLAUDE.md` "Project Structure" block; root `CONTEXT.md` glossary; `README.md`.

### 7.3 Ordering (dependency direction: `workbench-meta` → `workbench`, one-way)
1. Land the reorg in **`workbench`** as a single atomic commit (`git mv` to preserve history; all references in §7.2 updated in the same commit).
2. Then open the **`workbench-meta`** PR updating the 12 `domain` imports and re-pinning/reinstalling `workbench`. Never the reverse — meta depends on workbench.
3. Because only `domain` symbols move in the cross-repo surface, the window where meta is stale is bounded to "imports `workbench.models` which no longer exists" → meta CI fails loudly (not silently), so the sequencing is safe.

### 7.4 Verification (all must pass before the commit is final)
1. `grep -rEn '"workbench\.[a-z_.]+\.[A-Z][A-Za-z]*"' src/ config*.yml` → every hit resolves to an existing module (string-literal class paths).
1b. **Both import forms of every moved name are gone.** A single grep over all 14 moved top-level names covering dotted (`workbench.X`) **and** bare (`from workbench import X`) forms returns zero: `grep -rEn 'workbench\.(models|metrics|memory|main|registry|redaction|auth|middleware|config_writer|alerting|privacy|instrumentation|logging|usage_aggregator)\b|from[[:space:]]+workbench[[:space:]]+import[[:space:]].*\b(models|metrics|memory|main|registry|redaction|auth|middleware|config_writer|alerting|privacy|instrumentation|logging|usage_aggregator)\b' src/ tests/ scripts/ config*.yml`. (The AST/dotted-only checks miss the `from workbench import X` form.)
2. `ruff check src/ tests/` and `python -c "import workbench.runtime.app"` → static-import integrity (also proves `runtime/__init__.py` exists).
3. A pytest that walks every `class:` value in `config.example.yml` through `importlib.import_module` → proves dynamic resolution (catches the memory path change and any dangling provider path).
4. `pytest` (full suite) green; `tests/test_folder_docs.py` and `tests/test_domain_surface.py` green.
5. `make up` + `alembic upgrade head` via `entrypoint.sh` → end-to-end boot with the new `runtime.app:app`.
6. In `workbench-meta`: `pip install -e ../workbench && pytest` → proves the `domain` surface held.

## 8. CONTEXT.md / glossary updates

Add to the **authoritative** root `CONTEXT.md` (see §9):
- **Domain (package)**: the package holding the entity vocabulary (pydantic models + enums) the pipeline and API speak; replaces `models.py`. _Avoid_: "models" as a package name, "schema", "types", "entities".
- **Telemetry (package)**: modules emitting operational signals about the running system — metrics, structured logging (incl. the Sanitizing Processor), instrumentation wrappers, LLM usage aggregation, alerting. _Avoid_: "observability", "monitoring", "metrics" (too narrow), "utils".
- **Runtime (package)**: assembles the running ASGI app — app factory + app-level middleware (auth, correlation-id); hosts the entrypoint `workbench.runtime.app:app`. _Avoid_: "app" (collides with the `app` object), "service", "core", "server".
- **Package facade**: an `__init__.py` that re-exports its submodules' public symbols as the package's permanent interface; distinct from a back-compat shim (which preserves a deprecated name for later deletion). `domain/__init__.py` is a facade.
- **Package README**: every `__init__.py`-bearing dir under `src/workbench/` (except `__pycache__`, `migrations/versions`) carries a `README.md`; enforced by `tests/test_folder_docs.py`.
- Clarify under **Plugboard call sink**: `providers/llm/plugboard.py` defines `PlugboardCallRecord` + `record_plugboard_call`; it is deliberately Prometheus-free, so a provider importing it does not violate "providers never import `workbench.metrics`".

## 9. Pre-existing inconsistency: two CONTEXT.md files
Root `CONTEXT.md` (239 lines, richer) and `docs/CONTEXT.md` (205 lines) both exist; `tests/test_context_doc.py` guards `docs/CONTEXT.md`. **Resolution:** make the root `CONTEXT.md` authoritative (it is the fuller glossary and the one CLAUDE.md/skills reference), repoint `tests/test_context_doc.py` to `../CONTEXT.md`, and delete `docs/CONTEXT.md` (or replace with a one-line pointer). This is bundled into the reorg since the new glossary terms (§8) must land in exactly one enforced file.

## 10. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Silent break via string-literal class path | §7.1 grep in verification gate #1; #3 importlib walk of `config.example.yml`. |
| Existing local `config.yml` breaks on pull (memory path) | Document the one-line memory-path edit in PR/CHANGELOG; verification #3 catches it for `config.example.yml`. |
| `workbench-meta` stale window | One-way ordering (§7.3); meta CI fails loudly on missing `workbench.models`. |
| Circular imports after `domain` split | `enums.py` is a dependency-free leaf; `from __future__ import annotations` everywhere. |
| Large mechanical diff hides a real change | Pure move (`git mv`); no logic edits; full suite must be green pre-commit (verification #4). |
| README guard false positives | Explicit exclusion list (`__pycache__`, `migrations/versions`); guard asserts only existence + non-empty. |

## 11. Out of scope
`src/memory/` service package; `pipeline/`/`storage/`/`mcp/` internal restructure; `migrations/` relocation; any behavioral or API-contract change; renaming provider interface subfolders.
