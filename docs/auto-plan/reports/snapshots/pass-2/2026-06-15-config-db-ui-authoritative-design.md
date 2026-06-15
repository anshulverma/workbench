# Config → DB (UI-Authoritative) — Design Spec (Hardened)

> Auto-plan `--harden` artifact. Supersedes the draft at
> `docs/superpowers/specs/2026-06-15-config-db-ui-authoritative-design.md`.
> Decision log: `docs/auto-plan/reports/2026-06-15-config-db-ui-authoritative-state.json`.

## Context

Workbench config lives in `config.yml`, loaded via OmegaConf into a typed
`AppConfig` at startup (`config/loader.py`, `config/models.py`). Sources and the
messenger are UI-editable; those edits write **back to `config.yml`** via a
`ruamel.yaml` round-trip and hot-reload the affected provider (ADR 0013). At
startup every YAML source is also upserted into a `source_configs` table that the
read APIs query — so source definitions live in **two places** (YAML
authoritative, DB mirror), kept in sync by a startup re-sync and a dual-write.

The management UI has become the place config is actually viewed and changed. The
YAML-authoritative-with-DB-mirror arrangement is now the awkward middle: the
dual-write and startup re-sync exist only to keep the file and the table
agreeing, and "the same info in two places" is a standing source of confusion.

This spec makes the **DB the single source of truth** for operational config,
makes the **UI authoritative** for editing, moves **secrets + bootstrap to a
gitignored `.env`**, removes `config.yml` and the ruamel write-back (ADR 0013),
and makes **every operational section hot-apply**.

It reverses **ADR 0005** (YAML config) and **ADR 0013** (write-back), reverses
**ADR 0029** (presentation restart-only), and amends **ADR 0017** (secret
exposure). A single new **ADR 0055** records the reversal.

## Goals

1. **Two-tier config** — `.env` (gitignored) holds secrets + bootstrap needed
   before the DB is reachable; the DB holds every other `AppConfig` section.
2. **DB authoritative** — no `config.yml`. Sources live only in `source_configs`;
   all other Tier-2 sections live in a single JSONB **settings document**. The
   YAML→DB startup re-sync and dual-write are removed.
3. **UI authoritative** — a full settings UI edits every Tier-2 section through
   the API; nothing edits a file.
4. **Secrets stay out of the DB** — the document stores `${oc.env:...}`
   references only; values resolve from `.env`; the API never returns resolved
   secrets.
5. **Everything UI-editable hot-applies** — including live worker-pool resize,
   scheduler reconfig, and presentation (superseding ADR 0029).
6. **One-time import** — first boot imports the existing `config.yml` (or a
   `WORKBENCH_CONFIG_SEED`) into the DB, then `config.yml` is removed.
7. **`AppConfig` stays the in-memory shape** — downstream reads `app.state.config`;
   only assembly, persistence, and hot-apply change.

## Non-Goals

- Server-side writing of `.env`. The UI manages env-var **references**; values
  are placed in `.env` out-of-band.
- A full workbench-meta migration. This spec defines the generic **seed seam**
  (`WORKBENCH_CONFIG_SEED`) workbench-meta will use; the Meta-side migration
  (dropping its `config.meta.yml` override mount) is a separate effort in that
  repo, coordinated via ADR 0055.
- Multi-user config, RBAC, optimistic concurrency.
- Versioned config history / rollback in the DB.

## Tier Classification

**Tier 1 — `.env` (gitignored, read once at startup, read-only in UI):**

| Setting | Env var | Why bootstrap |
|---|---|---|
| Postgres DSN | `WORKBENCH_POSTGRES_DSN` | Needed to reach the DB; **required, hard-fail if unset** (`StorageConfig.postgres_dsn` has no pydantic default) |
| Server host/port/debug | `WORKBENCH_HOST` / `WORKBENCH_PORT` / `WORKBENCH_DEBUG` | Used to bind uvicorn **before** the lifespan/DB. Today `__main__.py`/`cli_main` read these off `config.server` loaded from `config.yml`; with the file removed both entrypoints **must be converted** to build `BootstrapConfig` from `os.environ` and bind from it, or boot hard-exits on the missing file (`loader.py:13-16`) |
| API token | `WORKBENCH_API_TOKEN` | Auth must exist at startup; secret. No rotation exists today — token is `.env`-only |
| Logging | `WORKBENCH_LOG_DIR` / `WORKBENCH_LOG_LEVEL` / `WORKBENCH_LOG_FORMAT` | Logger initialized before DB connect. **New vars** — today only `WORKBENCH_LOG_DIR` is read |
| Provider secret **values** | `ANTHROPIC_API_KEY`, `GOOGLE_CHAT_SPACE_ID`, `GOOGLE_CHAT_SA_KEY_PATH`, Google connection creds, … | Secrets; never in DB |

**Tier 2 — DB (settings document or `source_configs`), UI-editable, hot-applied:**
`llm`, `queue`, `triage`, `pipeline`, `batching`, `scheduler`, `messenger`,
`enrichment`, `presentation`, `memory`, `metrics`, `debug`, `privacy`, `tracing`,
`retention`, `alerting`, `connections`, and `sources` (own table).

**Decisions / edge cases (from grilling):**
- **`server.debug` (Tier 1) vs the `debug` section (`DebugConfig`, Tier 2)** are
  distinct concepts; keep them separate and disambiguate in docs.
- **`debug` (Tier 2)** is safe in the DB: `DebugConfig.sql_queries` gates the
  asyncpg pool created *after* the DB read.
- **`tracing` (Tier 2)** is safe: no tracer is initialized in the lifespan today.
- **`privacy` ordering hazard.** `privacy` is Tier 2 but the `SanitizingProcessor`
  is built during pre-DB logging setup. Resolution: pre-DB logging uses a
  `SanitizingProcessor` built from **`PrivacyConfig` pydantic defaults** (safe:
  sanitize on, redact emails/phones); after the DB read, re-apply logging if the
  persisted `privacy` differs. (`privacy` stays Tier 2.)
- **`version`.** The file-level semver schema-compat concept does not survive as
  a `.env` value. A `schema_version` key in the settings document carries the
  major-compat check (same rule as `loader.py`); document-shape migrations are
  Alembic's job. `AppConfig.version` keeps its pydantic default as the in-memory
  shape.

## Architecture

### Entry points (binding uvicorn before the lifespan)

`__main__.py:main` and `app.py:cli_main` call `uvicorn.run(host=…, port=…,
reload=…)` **before** the FastAPI lifespan runs, and today source those values
from `load_config(config.yml).server`. Removing `config.yml` breaks both, because
`load_config` hard-exits when the file is absent (`loader.py:13-16`). Both
entrypoints are converted to: `load_dotenv(override=False)` → build
`BootstrapConfig` from `os.environ` → bind uvicorn from `bootstrap.host/port` and
`reload=bootstrap.debug`. The full `AppConfig` is still assembled later inside the
lifespan (after the DB connect). `app.py:get_config()` (which also calls
`load_config`) is removed/replaced accordingly.

### Storage

- **`app_settings` table** (migration `010_app_settings.py`): a **single-row**
  JSONB document. Singleton enforced by `id INTEGER PRIMARY KEY DEFAULT 1` +
  `CHECK (id = 1)`; columns `id`, `data JSONB`, `updated_at TIMESTAMPTZ`. Upserts
  via `INSERT ... ON CONFLICT (id) DO UPDATE` (matches existing `upsert_source` /
  `PgConfigStore.set` idiom). The document is a **sparse override** — only
  non-default values — deep-merged over pydantic defaults at assembly.
  `${oc.env:...}` placeholders are stored **unresolved**.
- **`source_configs` table**: schema unchanged (the `relevance` JSONB from
  migration 008 is the last needed column). Becomes the **sole authority** for
  sources; the startup YAML→DB sync (`app.py:177-220`) and ruamel write-back are
  removed.
- **`config` KV table**: retained, scoped purely to **runtime state**
  (watermarks `source_last_polled:*`). It no longer backs user config editing.

### Stores

- New `SettingsStore` interface (`storage/base.py`) + `PgSettingsStore`
  (`storage/postgres/settings.py`): `get_document() -> dict | None`,
  `replace_document(data)`, `patch_section(name, value) -> dict`.
  Top-level-section granularity; nested sub-sections (`queue.scorer`,
  `alerting.conditions`) ride inside their top-level parent. `get_document()`
  returns `None` when no row exists — the **first-boot signal**.
- `patch_section` is read-modify-write executed **inside the same `reload_lock`
  critical section** as `apply_settings`, so no optimistic locking is needed
  (single-user, serialized writes).

### Sparse-document upgrade safety

The document stores only non-default overrides, so new pydantic defaults are
picked up automatically on upgrade. To survive a pydantic field rename/removal, a
stale override key must not crash boot: **set `model_config = ConfigDict(extra="ignore")`
on the config models**. The current models declare no `model_config`, so the
pydantic default (`extra="ignore"`) already applies — this change makes the
behavior explicit and load-bearing rather than incidental.

### Config assembly (replaces `config/loader.py:load_config`)

1. `load_dotenv()` populates `os.environ` from `.env` (`override=False` — real
   process env wins; matches container/Podman deploys injecting real env vars).
2. Build **`BootstrapConfig`** from `os.environ` (DSN, host, port, debug,
   api_token, logging). **Hard-fail with a clear message if `WORKBENCH_POSTGRES_DSN`
   is unset.** Initialize logging here (pre-DB), using `PrivacyConfig` defaults
   for the sanitizer.
3. Connect to the DB. Read `app_settings.data` (document) + `source_configs`.
4. **One-time import** if the document is absent (see below).
5. Assemble: `pydantic defaults` ⨉ `deep-merge(settings document)` ⨉ `sources`
   ⨉ `Tier-1 values (last)`, then `OmegaConf.create(...)` →
   `to_container(resolve=True)` to resolve `${oc.env:...}` → `AppConfig(**resolved)`.
   Tiers are **disjoint** (no key overlap); Tier-1-last is defensive.
6. Store at `app.state.config`. If the persisted `privacy` differs from defaults,
   re-apply logging now.

`load_config_from_string` is retained for tests; the file-required
`load_config(path)` and `WORKBENCH_CONFIG_OVERRIDE` file-merge are removed.

### One-time import & seed seam

On first boot when `app_settings` has **no row**:
1. Resolve the seed source: `WORKBENCH_CONFIG_SEED` if set, else `WORKBENCH_CONFIG`
   (default `config.yml`) if the file exists.
2. Parse it **unresolved** (OmegaConf load without `resolve`), preserving
   `${oc.env:...}`. Lift Tier-2 singleton sections into the document **without
   running resolve-validation** (so secrets are never baked in). Map sources
   (incl. `class`, `config`, `schedule`, `enabled`, `relevance`, `change_detector`)
   into `source_configs` via the existing `source_id_for` derivation.
3. Write the document **atomically and non-empty** (a crash mid-import must not
   leave a `{}` that falsely signals "imported"). Seed `schema_version`.
4. If no seed exists, leave the row absent and run on pydantic defaults (still
   requires a DSN to have reached the DB at all).

`config.yml` is deleted from the repo after the import path lands; the importer
remains for any stale local file but is a no-op once a document exists.
**workbench-meta** uses `WORKBENCH_CONFIG_SEED` (pointing at its `config.meta.yml`
content) for its first-boot seed; its full migration is a separate effort.

### Hot-apply

Generalize today's `reload_lock` + copy-on-write swap into
`apply_settings(new_document)`:

1. Acquire `reload_lock`.
2. Assemble + validate the candidate `AppConfig` (same pipeline as startup, minus
   DB read). Validation failure → nothing changes; return the error.
3. **Construct-all-then-swap-all for singleton providers**: build every new
   provider instance for changed provider sections first; only if *all* succeed,
   swap them in. (Cheap to build; closest to atomic. Sources/scheduler keep their
   existing incremental mutation.)
4. Diff per top-level section to route to appliers; each applier does its own
   **sub-field comparison** (e.g. the `queue` applier rebuilds the scorer only if
   `queue.scorer` changed, resizes the pool only if `queue.worker_concurrency`
   changed).

| Section(s) | Applier action |
|---|---|
| `llm`, `queue.scorer`, `enrichment`, `presentation`, `memory`, `messenger` | Construct new → swap into `app.state` → `close()` old. Messenger also calls `scheduler.set_messenger(new)` (updates `scheduler.messenger` + `alert_manager._messenger`). Presentation swaps `app.state.presenter` + `scheduler.presenter` + `pipeline.content_generators`. |
| `connections` | Rebuild the connection, then rebuild adapters/enrichers referencing it — requires a **connection→dependents reverse index** (new; see below). |
| `sources` | Existing `add_source_job` / `reschedule_source_job` / `remove_source_job`. |
| `queue.worker_concurrency` | `IngestionQueueWorker.set_concurrency(n)`: swap in a fresh `asyncio.Semaphore(n)`, update `self.concurrency`; do not cancel the loop. In-flight tasks release to the old semaphore; transient over-subscription for one batch is accepted (single-user). |
| `scheduler.poll_interval_minutes` | Reschedule the `alert_check` interval job (per-source polls use per-source cron, unaffected — ADR 0014). |
| `scheduler.morning_briefing_hour` | Reschedule the `briefing` cron job. |
| `triage.triage_poll_interval_seconds` | Reschedule the `triage_queue` interval job. |
| `alerting.enabled` | Add/remove the `alert_check` job. |
| `pipeline`, `triage` (caps/expiry), `batching` | **Live-mutate the engine** via new setters (`set_thresholds`, `set_batching`, `set_triage_expiry`), modeled on the existing `set_source_thresholds` — `PipelineEngine` captures these at construction, so a config swap alone does NOT reach them. |
| `retention`, `metrics`, `debug`, `privacy`, `tracing` | Read fresh from config; covered by the `app.state.config` swap + `scheduler.config` rebind. |

5. **Rebind `scheduler.config = new_config`** on every apply (the scheduler reads
   `daily_cap`/`retention`/`batching`/`expiry_days` off its own captured
   reference, separate from `app.state.config`).
6. Copy-on-write swap `app.state.config` last.

**Connection→dependents reverse index (new machinery).** Connections are
restart-only today; making them hot-apply requires tracking which adapters/
enrichers were built with each connection name, so a connection rebuild can
cascade. Record the connection name on each built adapter/enricher (or a
name→dependents map in `app.state`) at construction and at source hot-add.

**Persist vs apply ordering:** `validate → persist (DB) → apply`. The DB is the
single source of truth (D1); persisting first guarantees a restart converges to
the user's intent. An apply failure after persist leaves live state lagging the
DB until restart (the correct convergence direction); the PATCH response carries
the apply outcome, and `GET /api/settings` exposes a live-vs-persisted drift flag.

**Failure transactionality:** validate-all-then-(construct-all-then-swap-all) for
singleton providers makes provider changes effectively atomic. Sources/scheduler
mutate incrementally; a mid-apply failure there stops, leaves applied sections
applied, does not swap `app.state.config`, and surfaces a partial-apply error
naming the failed section.

### API

- New `api/settings.py`:
  - `GET /api/settings` — effective merged config, **redacted**, section-organized,
    with per-section "live vs restart-only" metadata, a **live-vs-persisted drift**
    flag, and per-secret-field resolution status `{env_var, resolvable}` (where
    `resolvable = env_var in os.environ`; never the value).
  - `PATCH /api/settings/{section}` — validate candidate → persist via
    `patch_section` → `apply_settings`. On a settings PATCH, **re-run
    `load_dotenv(override=False)`** so newly-added `.env` vars resolve live.
    Emits a `settings_section_updated` audit log with the Correlation ID and
    changed field **names** (ADR 0017). Section granularity only (no whole-doc PATCH).
- Secret fields are identified by **schema metadata** (`ProviderConfig` marks a
  field secret, e.g. `x-secret`), not by string-sniffing. PATCH **rejects** a raw
  literal in a known-secret field (must match `^\$\{oc\.env:[A-Za-z_]\w*\}$`),
  422. **Redaction vs env-ref disclosure:** the GET body never exposes a secret
  field's value *or* its `${oc.env:...}` reference string in the field's own
  position — `redact_secrets()` runs on GET as a fail-closed backstop and replaces
  any secret-keyed value (including the env-ref string) with `[REDACTED]`. The
  env-var **name** the UI needs is surfaced *only* via the separate per-field
  resolution map `{env_var, resolvable}`, computed from the **unredacted**
  in-memory document (the env_var name is not itself a secret). So "stored as a
  `${oc.env:...}` reference" describes persistence, not the GET body. The
  `adapter_type`/provider-class allowlist (ADR 0017) extends to any provider-`class:`
  field editable through `/api/settings` (no raw dotted paths from the browser).
- Existing `sources` / `connections` / `messenger` / `enrichers` APIs keep their
  external shapes; persistence re-points from `config/writer.py` to
  `SettingsStore` / `source_configs`. **Connections become editable + hot-applied**
  via `PATCH /api/settings/connections` (connections is a top-level settings-
  document section) — the write surface is the settings API, not a new route on
  `connections.py` (which keeps its GET names+health shape). Remove the hardcoded
  "connections are YAML-only + restart" string in `sources.py:103` and the
  "defined in YAML / require a restart" note in the `connections.py` docstring.
- **Remove the public `/api/config` route** (no external consumer; the Settings
  page reads `/api/debug/config`). The `config` KV table stays internal.
- `api/auth_token.py`: keeps vending `config.server.api_token` (now from `.env`);
  fix the stale docstring describing a cookie/query scheme.

### UI

Extend the existing `Settings.tsx` tab-container (HashRouter, ADR 0018). ~14
sections grouped into **category tabs** (General, Pipeline, Providers, Sources,
Messenger, Observability) with fine-grained sections as cards within each tab.
`SettingsSystem` is absorbed into a read-only **General** tab (server/storage/
logging from `.env`, "set via `.env`, restart to change"); its JSON-dump sections
become editable forms. `Sources` and `Messenger` editors fold in unchanged.

- **Forms:** schema-assisted hand-written per section (matching the existing
  `SourceForm` + `/api/sources/adapter-types` pattern), fed by per-section field
  metadata from `GET /api/settings`. Not a generic schema renderer (poor UX for
  nested dict/list sections; over-engineered for one user). Provider-class fields
  render as **server-allowlisted dropdowns**, never free text.
- **`EnvRefInput` component:** holds an env-var **name**, renders a resolved/
  unresolved badge (reuse `HealthBadge`), never an input holding a value; when
  unresolved shows "Set `<NAME>` in `.env`" inline. Status from the `GET /api/settings`
  resolution map.
- **Mutations:** pessimistic PATCH → invalidate `['settings']` → refetch → toast
  (mirrors `useUpdateMessenger`). Apply failures surface the server error +
  `X-Request-ID`. Not optimistic (apply can fail at provider-rebuild after
  validation).
- **Validation:** lean on server (authoritative) + 422→inline-field mapping
  (promote the duplicated mapping helper from Messenger/SourceForm to `lib/`);
  minimal client-side structural checks only.
- **UI State Taxonomy:** loading/error/unauthorized/degraded all map; "memory not
  configured" / "no messenger" are degraded panels (forms still render — you
  configure *to* set them), not errors. "empty" is degenerate for a config page.
- **api-types regen:** regenerate `ui/src/lib/api-types.ts` after `/api/settings`
  lands (running server on :8421 + standalone Node per the npm-blocked
  constraint). Sequences UI work after the API slice.

## Data Flow

```
.env ──load_dotenv(override=False)──► os.environ
                           │
        ┌──────────────────┤
        ▼                  ▼
  BootstrapConfig     OmegaConf resolve ${oc.env:...}
  (DSN[req], server,       ▲
   logging, token)         │
        │            settings document (app_settings JSONB, sparse, placeholders)
        ▼            + sources (source_configs)
   connect DB ───────► deep-merge over pydantic defaults  ──► AppConfig ──► app.state.config
        │                                                          ▲
        └─ first boot, no row ─► import seed (WORKBENCH_CONFIG_SEED|config.yml)
   UI ──PATCH /api/settings/{section}──► reload_dotenv → validate → persist → apply_settings
                                          (diff + appliers + scheduler.config rebind, under reload_lock)
```

## Error Handling

- **Invalid PATCH:** validate candidate before persist → 422; DB + live state
  untouched.
- **Provider rebuild failure:** construct-all-then-swap-all aborts before any
  swap for provider sections; surfaced to the caller; DB-authoritative on restart.
- **Unresolvable env-ref on PATCH:** after `reload_dotenv`, if still unset →
  reject 422 ("set `<VAR>` in `.env`").
- **Missing DSN at startup:** `BootstrapConfig` hard-fails with a clear message
  (in both the entrypoint binding path and the lifespan assembly path).
- **First boot, no seed:** all defaults; `sources: []`, console messenger.

## Testing

- **Backend unit:** `SettingsStore` round-trips + single-row invariant; assembly
  (defaults ⨉ document ⨉ sources ⨉ env-resolve; real-env-wins; unset-secret
  fails fast; `extra="ignore"` drops stale keys); one-time import (seed →
  document + `source_configs`, idempotent, no-seed → defaults, secrets not baked);
  redaction (no resolved secret in GET; secret-keyed value is `[REDACTED]` in the
  body; `{env_var, resolvable}` flags computed from the unredacted document);
  per-section appliers incl. validation-failure-leaves-state-unchanged.
- **Bootstrap/entrypoint:** `BootstrapConfig` reads host/port/debug/DSN/logging
  from `os.environ`; `__main__`/`cli_main` bind from it without touching
  `config.yml`; missing DSN hard-fails.
- **Hot-apply hard cases:** worker-pool `set_concurrency` (needs an introspection
  hook to assert new size); scheduler reschedule (assert next-run changed);
  engine live-mutation setters; `scheduler.config` rebind; connection cascade.
- **API integration:** PATCH → persist → live-effect (resize/reschedule);
  raw-secret rejection; `reload_dotenv` picks up a new var; audit log emitted.
- **Migration `010`** + first-boot import path.
- **Frontend (vitest):** per-section form render/validate/save; `EnvRefInput`
  badge; read-only General; 422→inline mapping.
- **Removals:** delete `config/writer.py` tests.
- **Pyramid:** heavy backend unit, medium frontend component, thin API-level
  integration for hot-apply (no in-repo browser e2e harness; full browser e2e out
  of scope for a single-user tool).

## Migration / Rollout (no dual-authority window)

1. Add `python-dotenv`; commit `.env.example` (keys only); verify `.gitignore`
   already lists `.env` (it does — no-op).
2. Migration `010_app_settings.py` (DDL only, no seed row).
3. **Single cutover step:** introduce DB-read assembly + one-time import, convert
   the `__main__`/`cli_main` entrypoints to bind uvicorn from `BootstrapConfig`,
   **and in the same step remove** the YAML→DB sync (`app.py:177-220`) and the
   ruamel write-back, so there is never a window where both YAML and DB are
   authoritative. `config.yml`/seed remains readable for first-boot import only.
4. Add `/api/settings` + `apply_settings` (incl. worker/scheduler/engine live
   mutators, connection reverse index); re-point existing config APIs; remove
   `/api/config`.
5. Build the settings UI; regenerate `api-types.ts`.
6. Delete `config.yml` and `config/writer.py`; final glossary/README/ADR updates.

## Documentation & Decisions

- **ADR 0055** — "DB-authoritative config with `.env` bootstrap; `config.yml`
  removed." Multi-decision (DB authority; two-tier `.env`; all-sections hot-apply
  incl. presentation; one-time import + seed seam; cross-repo coordination note).
  **Supersedes 0005, 0013, 0029; amends 0017.**
- **CONTEXT.md glossary** — update ~15 terms: "Config File" (→ split into
  **Bootstrap Config (`.env`)** + **Settings Document**), retire **Config
  Write-Back**, redefine **Targeted Hot-Reload** → **apply_settings**, fix
  **ProviderConfig** `_Avoid_` note (no `Settings` class exists; "settings" is not
  reserved), update **Source Adapter / Provider / Provider Registry / Memory
  Layer / Connection** ("from YAML" → "from DB"), confirm **Watermark** unaffected
  (stays in `config` KV), re-revise **Dropped concepts** (pydantic-settings,
  POST/DELETE /api/sources, POST /api/reload), update the **Example dialogue**
  (`worker_concurrency` via UI), and **Card Presenter** (now hot-applies). Add
  new terms: **Settings Document**, **Bootstrap Config (`.env`)**, **Settings
  Store**, **apply_settings**, **applier**, **Env-ref Input**, **Resolution
  Status**.
- **Per-package READMEs** (ADR 0054): `config/`, `storage/`, `api/`, `runtime/`.
- **`.env.example`** committed; `.gitignore` verified.
- **Memory:** `feedback_config_write_back.md` rewritten (done during planning).

## Open Items for Planning

- **Connection reverse-index** mechanism (exact shape) — the one piece of
  genuinely new machinery; sequence as its own plan step with focused tests.
- **Worker/scheduler introspection hooks** for live-effect assertions.
- **`extra=` policy** on the config models — verify and convert to `ignore` if
  needed.
