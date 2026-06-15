# Config → DB (UI-Authoritative) — Implementation Plan

Spec: `docs/auto-plan/specs/2026-06-15-config-db-ui-authoritative-design.md`
ADR: `docs/adr/0055-db-authoritative-config-with-env-bootstrap.md`

Slices are ordered so the server boots at every step with **no dual-authority
window**: the YAML→DB sync and ruamel write-back are deleted in the *same* slice
(Slice 2) that introduces DB-read assembly.

---

## Slice 1: Storage foundation — `app_settings`, `SettingsStore`, sparse-merge safety

**Title:** Migration 010, `SettingsStore` interface + PG impl, config-model `extra` policy

**Description:** Pure storage groundwork; no behavior change yet. Add the single-row
`app_settings` table (`id INTEGER PRIMARY KEY DEFAULT 1, CHECK (id = 1)`, `data
JSONB`, `updated_at TIMESTAMPTZ`), DDL only (no seed row — absence of a row is the
first-boot signal). Add the `SettingsStore` ABC and `PgSettingsStore`
(`get_document() -> dict | None`, `replace_document(data)`,
`patch_section(name, value) -> dict`, upsert via `ON CONFLICT (id) DO UPDATE`).
Wire the store into the `Stores` bundle as a keyword-only param. Set
`model_config = ConfigDict(extra="ignore")` on `AppConfig` and section models so a
stale override key from a renamed field never crashes boot.

**Files to create:**
- `src/workbench/migrations/versions/010_app_settings.py` — create `app_settings` (DDL only)
- `src/workbench/storage/postgres/settings.py` — `PgSettingsStore`

**Files to modify:**
- `src/workbench/storage/base.py` — `SettingsStore` ABC; add `settings` to `Stores` (keyword-only)
- `src/workbench/storage/postgres/stores.py` — wire `PgSettingsStore` into `create_postgres_stores`
- `src/workbench/config/models.py` — `extra="ignore"` on `AppConfig` + section models; add optional `schema_version` handling

**Tests:**
- `tests/test_settings_store.py` — get/replace/patch round-trips; `get_document` returns `None` when absent; single-row invariant (second insert upserts, never a 2nd row); `patch_section` deep-merge semantics (dict merge, list/scalar replace)
- `tests/test_config_models_extra.py` — unknown top-level key is ignored, not fatal

**Complexity:** S · **Dependencies:** none · **Parallelizable with:** none (foundation)

---

## Slice 2: Config assembly cutover — `.env` bootstrap, DB-read, one-time import (removes dual authority)

**Title:** `BootstrapConfig` + `python-dotenv`, DB-backed assembly, seed import, entrypoint binding; delete YAML→DB sync + write-back

**Description:** The cutover. Add `python-dotenv`. New assembly: `load_dotenv(override=False)`
→ build `BootstrapConfig` from `os.environ` (DSN **required, hard-fail if unset**;
host/port/debug; logging dir/level/format — adding the new `WORKBENCH_LOG_LEVEL`/
`WORKBENCH_LOG_FORMAT`/`WORKBENCH_HOST`/`WORKBENCH_PORT`/`WORKBENCH_DEBUG` reads)
→ init logging pre-DB using `PrivacyConfig` defaults for the sanitizer → connect DB
→ read `app_settings` document + `source_configs` → **one-time import** if no row
(seed = `WORKBENCH_CONFIG_SEED` else `WORKBENCH_CONFIG`/`config.yml`; parse
unresolved, lift Tier-2 sections + map sources via `source_id_for`, write atomic
non-empty, seed `schema_version`; never resolve-validate before persist) →
deep-merge document over pydantic defaults ⨉ sources ⨉ Tier-1-last → OmegaConf
resolve → `AppConfig` → `app.state.config` → re-apply logging if persisted
`privacy` differs. **Convert the uvicorn-binding entrypoints**: `__main__.py:main`
and `app.py:cli_main` (and `app.py:get_config`) currently call
`load_config(config.yml)` and bind from `config.server`; after removal
`load_config` hard-exits (`loader.py:13-16`), so both must instead
`load_dotenv(override=False)` → build `BootstrapConfig` → `uvicorn.run(host=
bootstrap.host, port=bootstrap.port, reload=bootstrap.debug)`. **In the same
slice**, delete the YAML→DB upsert (`app.py:177-220`), the ruamel write-back
calls, the file-required `load_config(path)`, and the `WORKBENCH_CONFIG_OVERRIDE`
file-merge.

**Files to create:**
- `src/workbench/config/bootstrap.py` — `BootstrapConfig` (reads `os.environ`, hard-fails on missing DSN; standalone-constructible for the entrypoints)
- `src/workbench/config/assembly.py` — `assemble_config(stores, bootstrap)` (merge + resolve → `AppConfig`)
- `src/workbench/config/importer.py` — first-boot seed import (`config.yml`/seed → document + `source_configs`)

**Files to modify:**
- `src/workbench/config/loader.py` — remove file-required path + `CONFIG_OVERRIDE`; keep `load_config_from_string` for tests
- `src/workbench/runtime/app.py` — new lifespan startup sequence; convert `cli_main` + remove/replace `get_config` to bind from `BootstrapConfig`; **remove** YAML→DB sync (177-220) and ruamel write-back
- `src/workbench/__main__.py` — bind uvicorn from `BootstrapConfig` instead of `load_config(config.yml)`
- `pyproject.toml` — add `python-dotenv`
- `.env.example` (new at repo root) — keys only

**Tests:**
- `tests/test_config_assembly.py` — defaults ⨉ document ⨉ sources ⨉ env-resolve; real env wins over `.env`; unset referenced secret fails fast; missing DSN hard-fails
- `tests/test_config_bootstrap.py` — `BootstrapConfig` reads host/port/debug/DSN/logging from `os.environ`; `__main__`/`cli_main` bind without reading `config.yml` (patch `uvicorn.run`, assert host/port/reload from env); missing DSN hard-fails
- `tests/test_config_importer.py` — seed → document + `source_configs`; idempotent (2nd boot no-op); no-seed → defaults; secrets stored unresolved (not baked); `change_detector`/`relevance` mapped
- Update existing startup tests that assumed YAML load

**Complexity:** L · **Dependencies:** Slice 1 · **Parallelizable with:** none

---

## Slice 3: Hot-apply engine — `apply_settings`, live worker/scheduler/engine mutation, connection cascade

**Title:** Generalized `apply_settings` with per-section appliers and live-reconfig hooks

**Description:** Generalize the `reload_lock` + copy-on-write swap into
`apply_settings(new_document)`: assemble+validate candidate → construct-all-then-
swap-all for provider sections (incremental for sources/scheduler) → per-section
appliers (each sub-field-diffs) → rebind `scheduler.config` → swap
`app.state.config` last. Add the live-reconfig hooks the grilling found necessary:
`IngestionQueueWorker.set_concurrency(n)` (swap semaphore, no loop cancel);
scheduler reschedule helpers (`alert_check` interval, `briefing` cron,
`triage_queue` interval, add/remove `alert_check` on `alerting.enabled`);
`PipelineEngine` setters (`set_thresholds`, `set_batching`, `set_triage_expiry`)
since it captures these at construction; messenger applier calls
`scheduler.set_messenger`; presentation applier swaps `app.state.presenter` +
`scheduler.presenter` + `pipeline.content_generators` (supersedes ADR 0029). Add a
**connection→dependents reverse index** (record each adapter/enricher's connection
name at construction + source hot-add) so a connection rebuild cascades.

**Files to create:**
- `src/workbench/runtime/apply_settings.py` — `apply_settings` + applier registry

**Files to modify:**
- `src/workbench/pipeline/worker.py` — `set_concurrency(n)`
- `src/workbench/pipeline/scheduler.py` — reschedule helpers; expose `config` rebind; reverse-index hooks
- `src/workbench/pipeline/engine.py` — `set_thresholds` / `set_batching` / `set_triage_expiry`
- `src/workbench/providers/registry.py` — record connection name on built adapters/enrichers (reverse index)
- `src/workbench/runtime/app.py` — build the reverse index at startup; expose live objects on `app.state`

**Tests:**
- `tests/test_apply_settings.py` — per-section appliers; validation-failure leaves state unchanged; construct-all-then-swap-all atomicity; partial-apply error surfaces failed section; `scheduler.config` rebind
- `tests/test_worker_resize.py` — `set_concurrency` changes effective size (introspection hook); in-flight tasks unaffected
- `tests/test_scheduler_reconfig.py` — reschedule changes next-run; `alerting.enabled` add/remove
- `tests/test_engine_live_mutation.py` — setters change behavior without rebuild
- `tests/test_connection_cascade.py` — connection rebuild rebuilds dependents

**Complexity:** XL · **Dependencies:** Slice 2 · **Parallelizable with:** Slice 4 (API) partially

---

## Slice 4: API — `/api/settings`, re-point existing APIs, remove `/api/config`

**Title:** `/api/settings` GET/PATCH with redaction + resolution-status; re-point persistence; audit + secret rules

**Description:** Add `api/settings.py`: `GET /api/settings` (effective merged
config, redacted, section-organized, per-section live-vs-restart metadata,
live-vs-persisted drift flag, per-secret `{env_var, resolvable}` status — never
values). `PATCH /api/settings/{section}`: `load_dotenv(override=False)` → validate
candidate → persist via `patch_section` → `apply_settings`; reject raw literals in
known-secret fields (schema-metadata `x-secret`, must match
`^\$\{oc\.env:[A-Za-z_]\w*\}$`); emit `settings_section_updated` audit log with
Correlation ID + changed field names; `redact_secrets()` backstop. Extend the
provider-`class:` allowlist (ADR 0017) to settings-editable provider fields.
Re-point `sources`/`connections`/`messenger`/`enrichers` persistence to
`SettingsStore`/`source_configs` (external shapes unchanged); make `connections`
editable via `PATCH /api/settings/connections` (top-level section) + hot-applied,
remove the "connections are YAML-only + restart" string in `sources.py:103` and
the "defined in YAML / require a restart" note in the `connections.py` docstring.
Delete the public `/api/config` route (keep `/api/debug/config` and the `config`
KV store internal). Fix the `auth_token.py` docstring.

**Files to create:**
- `src/workbench/api/settings.py`

**Files to modify:**
- `src/workbench/api/sources.py`, `connections.py`, `messenger.py`, `enrichers.py` — re-point persistence; connections editable
- `src/workbench/api/redaction.py` — confirm coverage for `/api/settings`; secret-field reject helper
- `src/workbench/api/auth_token.py` — docstring fix
- `src/workbench/runtime/app.py` — register settings router; **unregister** `api/config.py` router
- `src/workbench/config/models.py` — `x-secret` schema metadata on secret provider fields

**Files to delete:**
- `src/workbench/api/config.py` (and its tests)

**Tests:**
- `tests/test_api_settings.py` — GET redaction (secret-keyed value is `[REDACTED]`, no resolved secret), resolution status, drift flag; PATCH persist→apply; raw-secret 422; `reload_dotenv` picks up a new var; audit log emitted; section granularity
- `tests/test_api_connections_hotapply.py` — connection PATCH via `/api/settings/connections` hot-applies + cascades
- Update `sources`/`messenger` API tests for the new persistence backend

**Complexity:** L · **Dependencies:** Slice 3 · **Parallelizable with:** Slice 3 (start once `apply_settings` signature is fixed)

---

## Slice 5: Settings UI — section shell, `EnvRefInput`, per-section forms

**Title:** Full settings UI extending `Settings.tsx`; env-ref fields; api-types regen

**Description:** Extend `Settings.tsx` tab-container with category tabs (General,
Pipeline, Providers, Sources, Messenger, Observability); fine-grained sections as
cards. Absorb `SettingsSystem` into a read-only **General** tab (server/storage/
logging from `.env`). Schema-assisted hand-written forms per section, fed by
`GET /api/settings` field metadata; provider-class fields = server-allowlisted
dropdowns. Add `EnvRefInput` (env-var name + resolved/unresolved `HealthBadge`,
never a value input; "set `<NAME>` in `.env`" when unresolved). Pessimistic PATCH
→ invalidate `['settings']` → toast; surface apply errors + `X-Request-ID`. Promote
the 422→inline-field mapping helper to `lib/`. Regenerate `api-types.ts` (running
server + standalone Node, npm-blocked path).

**Files to create:**
- `ui/src/hooks/useSettings.ts` — query + per-section mutation hooks (an existing `useSettings.ts` reads `/api/debug/config`; re-point its query to `GET /api/settings`)
- `ui/src/components/EnvRefInput.tsx`
- `ui/src/components/settings/*` — per-section form components
- `ui/src/lib/form-errors.ts` — shared 422→field mapper

**Files to modify:**
- `ui/src/pages/Settings.tsx` — category tabs + cards; absorb `SettingsSystem`
- `ui/src/pages/SettingsSystem.tsx` — reduce to read-only General content
- `ui/src/lib/api-types.ts` — regenerate after Slice 4 lands

**Tests:**
- `ui/src/components/EnvRefInput.test.tsx` — badge resolved/unresolved; no value rendered
- `ui/src/pages/Settings.test.tsx` — per-section render/validate/save; read-only General; 422→inline mapping

**Complexity:** XL · **Dependencies:** Slice 4 (API + regenerated types) · **Parallelizable with:** none

---

## Slice 6: Cutover cleanup + documentation

**Title:** Delete `config.yml`/`writer.py`; CONTEXT.md glossary, READMEs

**Description:** Remove `config.yml` from the repo and `config/writer.py` (+ tests).
Update CONTEXT.md (~15 terms: split "Config File" → **Bootstrap Config** +
**Settings Document**; retire **Config Write-Back**; **Targeted Hot-Reload** →
**apply_settings**; fix **ProviderConfig** `_Avoid_` note; "from YAML" → "from DB"
across Source Adapter/Provider/Registry/Memory Layer/Connection; re-revise Dropped
concepts; update Example dialogue + Card Presenter; add Settings Document /
Bootstrap Config / Settings Store / apply_settings / applier / Env-ref Input /
Resolution Status). Update `config/`, `storage/`, `api/`, `runtime/` READMEs.

**Files to modify:**
- `CONTEXT.md`, `src/workbench/config/README.md`, `storage/README.md`, `api/README.md`, `runtime/README.md`

**Files to delete:**
- `config.yml`, `src/workbench/config/writer.py` (+ `tests/test_config_writer*.py`)

**Tests:**
- `tests/test_folder_docs.py` still passes (READMEs non-empty)
- grep guard: no remaining `config.yml` / `ruamel` / `WORKBENCH_CONFIG_OVERRIDE` references in `src/`

**Complexity:** M · **Dependencies:** Slices 2–5 · **Parallelizable with:** none (final)

---

## Out of scope (follow-ups)
- **workbench-meta migration** — drop the `config.meta.yml` override mount, ship a
  `WORKBENCH_CONFIG_SEED`, move `server`/secrets to `.env`. Separate effort in that
  repo; coordinate per ADR 0055 (land workbench first).
- Browser e2e for hot-apply (no in-repo harness).
- Config history / rollback / export-to-YAML snapshot.
- Pre-existing latent bug (not introduced here): `scheduler.content_generators` is
  read in `_fire_retriage` (`scheduler.py:497`) but never assigned at construction;
  fix separately. The presentation applier targets `pipeline.content_generators`
  (the engine path that runs at ingest), which is correct and sufficient here.
