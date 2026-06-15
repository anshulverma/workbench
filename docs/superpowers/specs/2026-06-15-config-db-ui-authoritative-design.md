# Config → DB (UI-Authoritative) — Design Spec

## Context

Workbench config currently lives in `config.yml`, loaded via OmegaConf into a
typed `AppConfig` at startup (`config/loader.py`, `config/models.py`). Sources
and the messenger are editable from the UI; those edits write **back to
`config.yml`** via a `ruamel.yaml` round-trip and hot-reload the affected
provider (ADR 0013). At startup, every YAML source is also upserted into a
`source_configs` table that the read APIs query — so source definitions live in
**two places** (YAML authoritative, DB mirror), kept in sync by a startup
re-sync and a dual-write on every mutation.

As the management UI has grown (v4 System Status, funnel, dashboard, the
existing source/messenger/connection editors), the UI has become the place where
config is actually viewed and changed. The YAML-authoritative-with-DB-mirror
arrangement is now the awkward middle: the dual-write and startup re-sync exist
only to keep the file and the table agreeing, and "the same info in two places"
is a standing source of confusion.

This spec makes the **DB the single source of truth** for all operational
config, makes the **UI the authoritative editing surface**, moves **secrets and
bootstrap settings to a gitignored `.env`**, and **removes `config.yml`** (and
the ruamel write-back of ADR 0013) entirely.

This reverses the decision recorded in **ADR 0013** ("YAML remains the single
source of truth") and the corresponding project decision in `CLAUDE.md`. A new
ADR supersedes ADR 0013.

## Goals

1. **Two-tier config** — `.env` (gitignored) holds secrets + bootstrap settings
   needed before the DB is reachable; the DB holds every other `AppConfig`
   section.
2. **DB is authoritative** — no `config.yml`. Source definitions live only in
   `source_configs`; all other Tier-2 sections live in a single JSONB settings
   document. The YAML→DB startup re-sync and dual-write are removed.
3. **UI is authoritative** — a full settings UI edits every Tier-2 section.
   Reads and writes go through the API; nothing edits a file.
4. **Secrets stay out of the DB** — the DB stores `${oc.env:...}` references
   only; values resolve from `.env` at instantiation; the API never returns
   resolved secrets.
5. **Everything UI-editable hot-applies** — changing any Tier-2 section takes
   effect in-process with no restart, including live worker-pool resize and
   scheduler reconfiguration.
6. **One-time import** — on first boot with an empty settings document, the
   existing `config.yml` is imported (unresolved), then the file is deleted.
7. **`AppConfig` stays the in-memory shape** — downstream code keeps reading
   `app.state.config`; only assembly and persistence change.

## Non-Goals

- Server-side writing of `.env`. The UI manages env-var **references**, not
  secret material; values are placed in `.env` out-of-band.
- Multi-user / multi-tenant config. This is a single-user tool; no per-user
  config, RBAC, or optimistic-concurrency machinery.
- Versioned config history / rollback in the DB. (A future export-to-YAML
  snapshot could provide this; out of scope here.)
- Changing the `WORKBENCH_CONFIG_OVERRIDE` mechanism beyond removing the
  file-based base it merged onto.

## Tier Classification

**Tier 1 — `.env` (gitignored, read once at startup, read-only in UI):**

| Setting | Env var | Why bootstrap |
|---|---|---|
| Postgres DSN | `WORKBENCH_POSTGRES_DSN` | Needed to reach the DB (chicken-and-egg) |
| Server host/port/debug | `WORKBENCH_HOST` / `WORKBENCH_PORT` / `WORKBENCH_DEBUG` | Bind happens before DB; can't meaningfully hot-rebind |
| API token | `WORKBENCH_API_TOKEN` | Auth must be available at startup; secret |
| Logging dir/level/format | `WORKBENCH_LOG_DIR` / `WORKBENCH_LOG_LEVEL` / `WORKBENCH_LOG_FORMAT` | Logger initialized before DB connect |
| All provider secrets | `ANTHROPIC_API_KEY`, `GOOGLE_CHAT_SPACE_ID`, `GOOGLE_CHAT_SA_KEY_PATH`, Google connection creds, … | Secrets; never in DB |

**Tier 2 — DB (JSONB settings document or `source_configs`), UI-editable,
hot-applied:**

`llm`, `queue` (scorer + worker_concurrency + retry knobs), `triage`,
`pipeline`, `batching`, `scheduler`, `messenger`, `enrichment`, `presentation`,
`memory`, `metrics`, `debug`, `privacy`, `tracing`, `retention`, `alerting`,
`connections`, and `sources` (the last in its own table).

**Decision (logging):** `logging` stays Tier 1 because the logger is initialized
before the DB is connected. It is shown read-only in the UI with a "set via
`.env`, restart to change" note. Server `host`/`port` likewise.

**Decision (secret references):** secret-bearing fields in the UI accept an
env-var **name** and show a resolved/unresolved badge. The actual value lives in
`.env`, edited by the user out-of-band. The server never writes `.env`. Adding a
new credential is a deliberate two-step: set the value in `.env`, then reference
it in the UI.

## Architecture

### Storage

- **`app_settings` table** (migration `010_app_settings.py`): a single-row JSONB
  document holding all Tier-2 **singleton** sections, with `${oc.env:...}`
  placeholders left **unresolved** for secrets. Single-row invariant enforced by
  a fixed primary key (e.g. `id = 1` with a check / `singleton BOOLEAN` unique).
  Columns: `id`, `data JSONB`, `updated_at`.
- **`source_configs` table**: schema unchanged (`id`, `adapter_type`, `config`
  JSONB, `schedule`, `enabled`, `relevance` JSONB, `created_at`). Becomes the
  **sole authority** for sources; the startup YAML→DB sync (`app.py:177-220`) is
  removed.
- **`config` KV table**: retained, scoped purely to **runtime state**
  (watermarks `source_last_polled:*`, and other runtime KV). It no longer backs
  any user-facing config editing; the public config API moves to `/api/settings`
  to avoid confusion with this table's `/api/config` route.

### Stores

- New `SettingsStore` interface (`storage/base.py`) + `PgSettingsStore`
  (`storage/postgres/settings.py`):
  - `get_document() -> dict | None`
  - `replace_document(data: dict) -> None`
  - `patch_section(name: str, value: Any) -> dict` (read-modify-write of one
    top-level section; returns the new full document)
- `SourceConfigStore` (`storage/postgres/sources.py`) is unchanged.

### Config assembly (replaces `config/loader.py:load_config`)

New startup flow:

1. `load_dotenv()` populates `os.environ` from `.env` (no-op if absent;
   real env vars still win).
2. Read **Tier-1 bootstrap** directly from `os.environ` into a small
   `BootstrapConfig` (DSN, host, port, debug, api_token, logging). Enough to
   connect to the DB and initialize logging.
3. Connect to the DB. Read `app_settings.data` (the document) and
   `source_configs` rows.
4. **One-time import** (see below) if the document is absent/empty.
5. Assemble the full config dict:
   `pydantic defaults` ⨉ `deep-merge(settings document)` ⨉ `sources from table`
   ⨉ `Tier-1 values`, then `OmegaConf.create(...)` →
   `OmegaConf.to_container(resolve=True)` to resolve `${oc.env:...}` against
   `os.environ` → `AppConfig(**resolved)`.
6. Store at `app.state.config` exactly as today.

`AppConfig` is unchanged as a shape, so `storage`/`server`/`logging` remain
fields — they're just populated from `.env` rather than the file.
`load_config_from_string` is retained for tests; the file-required
`load_config(path)` path is removed.

### One-time import

On first boot when `app_settings` has no document:

1. If a legacy `config.yml` exists (path from `WORKBENCH_CONFIG`, default
   `config.yml`):
   - Parse it **unresolved** (OmegaConf load without `resolve`, or ruamel),
     preserving `${oc.env:...}` placeholders.
   - Lift the Tier-2 **singleton** sections into the initial settings document.
   - Import `sources` into `source_configs` (the existing upsert logic, run
     once).
2. If no `config.yml` exists, write an empty document; everything falls back to
   pydantic defaults.
3. After a successful import, the import is idempotent (presence of a document
   means "already imported"). `config.yml` is deleted from the repo as part of
   this change; the import path remains for any developer with a stale local
   file but is a no-op once the document exists.

`config/writer.py` (ruamel write-back, ADR 0013) and its callers are removed
once nothing references them.

### Hot-apply

Generalize today's `reload_lock` + copy-on-write swap (sources/messenger only)
into `apply_settings(new_document)` on the app state:

1. Acquire `reload_lock`.
2. Assemble + validate the candidate `AppConfig` (same pipeline as startup,
   minus DB read). On validation failure, nothing changes; return the error.
3. Diff the candidate against the live `app.state.config` per top-level section.
4. For each changed section, run its registered **applier**:

| Section(s) | Applier action |
|---|---|
| `llm`, `queue.scorer`, `enrichment`, `presentation`, `memory`, `messenger` | Rebuild provider instance(s) from config; swap into `app.state` (and `scheduler.messenger` / `alert_manager.messenger` for messenger, per ADR 0013). |
| `sources` | Existing add / remove / reschedule job logic (`scheduler.add_source_job` / `reschedule_source_job` / `remove_source_job`). |
| `queue.worker_concurrency` | **Live-resize** the ingestion worker pool. |
| `scheduler.*` | Reschedule cron jobs (poll cadence, morning briefing). |
| `triage`, `pipeline`, `batching`, `retention`, `alerting`, `metrics`, `debug`, `privacy`, `tracing` | Swap `app.state.config`; these are read fresh at point of use. |
| `connections` | Rebuild the connection, then rebuild adapters/enrichers that reference it. |

5. Copy-on-write swap `app.state.config` last, so in-flight readers never see a
   half-applied config.

**Riskiest new units** (call out for the plan): live worker-pool resize and
live scheduler reconfiguration — the other appliers already have analogues in
the current reload path.

### API

- New `api/settings.py`:
  - `GET /api/settings` — effective merged config, **redacted** (secrets shown
    as their `${oc.env:...}` placeholder, never resolved), organized by section,
    with per-section "applies live vs read-only" metadata and per-secret-field
    resolution status.
  - `PATCH /api/settings/{section}` — validate the merged candidate → persist
    via `SettingsStore.patch_section` → `apply_settings`. Returns the updated,
    redacted section.
- Existing `sources` / `connections` / `messenger` / `enrichers` / `auth_token`
  APIs keep their external shapes but re-point persistence from YAML write-back
  to `SettingsStore` / `source_configs`. The `auth_token` API is reconciled with
  the `.env` bootstrap token during planning (token now originates from `.env`;
  decide whether rotation writes a runtime override or is removed).
- The old `/api/config` (generic KV) is retained only if still needed for
  runtime KV; otherwise its config-editing semantics move entirely to
  `/api/settings`. Redaction reuses `api/redaction.py`.

### UI

Reorganize the `Settings` page into section tabs/cards mirroring `AppConfig`:

- **General** (read-only): server host/port, storage DSN presence, logging — all
  from `.env`, with a "set via `.env`, restart to change" note.
- **LLM**, **Queue**, **Triage**, **Pipeline**, **Scheduler**, **Enrichment**,
  **Presentation**, **Memory**, **Messenger**, **Connections**, **Sources**,
  **Retention**, **Alerting**, **Observability** (metrics/debug/privacy/
  tracing).

Each editable section is a typed form (numbers / toggles / provider-class
selects) with client + server validation; save issues `PATCH
/api/settings/{section}` and a toast reflects the hot-apply result. Secret fields
render as **env-ref inputs** with a resolved/unresolved badge fed by the
settings status in `GET /api/settings`; they never display secret values. The
existing `SourceForm` / `Messenger` editors are folded under this shell rather
than rewritten.

## Data Flow

```
.env ──load_dotenv──► os.environ
                           │
        ┌──────────────────┤
        ▼                  ▼
  BootstrapConfig     OmegaConf resolve ${oc.env:...}
  (DSN, server,            ▲
   logging, token)         │
        │            settings document (app_settings JSONB, placeholders)
        ▼            + sources (source_configs)
   connect DB ───────► deep-merge over pydantic defaults
                           │
                           ▼
                      AppConfig  ──►  app.state.config
                           ▲
   UI ──PATCH /api/settings/{section}──► validate ──► SettingsStore.patch_section
                           │                                   │
                           └────────── apply_settings ◄────────┘
                                       (diff + per-section appliers, under reload_lock)
```

## Error Handling

- **Invalid PATCH:** assemble + validate the candidate `AppConfig` before
  persisting. On failure, return 422 with the validation error; the DB and
  `app.state.config` are untouched.
- **Provider rebuild failure during apply:** the offending section's applier
  raises; `apply_settings` aborts the swap for that section, leaves
  `app.state.config` unchanged, and surfaces the error to the API caller. (Same
  "validate → instantiate → swap; if instantiation fails nothing changes"
  invariant as ADR 0013.)
- **Missing `.env` / unresolved secret:** OmegaConf resolution of a referenced
  but unset env var fails fast at startup with a clear message; at runtime PATCH,
  the same resolution is part of validation, so an unresolved reference is
  rejected before persistence.
- **Empty DB on first boot, no `config.yml`:** all defaults; server starts with
  `sources: []` and console messenger defaults — same as a fresh install today.

## Testing

- **Settings store:** `get`/`replace`/`patch_section` round-trips; single-row
  invariant.
- **Config assembly:** defaults ⨉ document ⨉ sources ⨉ env resolution produces
  the expected `AppConfig`; real env vars override `.env`; unset referenced
  secret fails fast.
- **One-time import:** a sample `config.yml` imports into the document +
  `source_configs`; idempotent on second boot; no-file path yields defaults.
- **Secret redaction:** `GET /api/settings` never returns a resolved secret;
  placeholders preserved; resolution-status flags correct.
- **Hot-apply per section:** provider rebuild (llm/messenger/enrichment/memory),
  source add/remove/reschedule, worker-pool resize, scheduler reschedule,
  scalar-section swap. Validation-failure leaves state unchanged.
- **UI:** per-section form render / validate / save (extend existing
  `Settings.test.tsx`, `Sources.test.tsx`, `Messenger.test.tsx`); env-ref field
  shows correct badge; read-only General section.
- **Migration `010`:** creates `app_settings`; first-boot import path.
- **Removals:** delete tests tied to `config/writer.py`.

## Migration / Rollout

1. Add `python-dotenv` dependency; commit `.env.example` (keys, no values);
   add `.env` to `.gitignore`.
2. Add migration `010_app_settings.py`.
3. Land assembly + stores + one-time import behind the existing startup path;
   keep `config.yml` present for the first boot so the import runs.
4. Land `/api/settings` + hot-apply; re-point existing config APIs.
5. Land the settings UI.
6. Delete `config.yml`, `config/writer.py` (and ADR-0013 write-back), and the
   YAML→DB sync.
7. New ADR superseding ADR 0013; update `CLAUDE.md` design decisions and
   `config/`, `storage/`, `api/` READMEs.

## Documentation & Decisions

- **New ADR** (next available number) superseding **ADR 0013**: "DB-authoritative
  config with `.env` bootstrap; `config.yml` removed." Records the reversal and
  the secret-reference constraint.
- **`CLAUDE.md`**: replace the "YAML config … YAML stays source of truth"
  decision with the DB-authoritative + `.env` model.
- **Per-package READMEs**: `config/` (assembly from `.env` + DB, no file),
  `storage/` (`SettingsStore`), `api/` (`/api/settings`).
- **`.env.example`** committed; `.gitignore += .env`.

## Open Items for Planning

- Reconcile `api/auth_token.py` rotation with the `.env` bootstrap token.
- Confirm whether `/api/config` (KV) keeps any external consumers or is fully
  internalized to runtime state.
- Worker-pool live-resize and scheduler live-reconfig are the two units needing
  new live-reconfiguration hooks; sequence them as their own plan steps with
  focused tests.
