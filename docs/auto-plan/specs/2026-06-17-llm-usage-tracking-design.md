# LLM Usage Tracking — Design Spec

## Context

WorkBench makes many LLM calls across the pipeline (extraction, queue scoring, relevance filtering, triage-card generation, response interpretation) and inside the separate memory subservice (Graphiti). Today these calls are observable only as in-memory Prometheus counters plus a periodic `llm_usage_summary` log line; nothing persists a per-call record, and the **LLM Infra** sub-tab on the System Status page is wired to mock data (`buildDefaultLLMCalls()` + a `setInterval`). This spec defines durable, full-fidelity per-call capture (prompt, completion, structured output, tokens, latency, provenance), a query API, a live-tailing UI fed by real data, and rolling metrics.

## Goals

1. **Full-fidelity capture** — record every LLM call's origin, purpose, stage, system prompt, input prompt, completion, structured output, model, temperature, tokens (in/out/cache), latency, status, and per-item batch breakdown.
2. **Durable per-call log** — persist calls to a new `llm_calls` table that is the source of truth for the LLM Infra page and a queryable history.
3. **Complete scope** — capture every component that calls an LLM: the workbench main LLM provider, the queue scorer, and the memory subservice (Graphiti) at full fidelity.
4. **Live tail + detail** — replace the UI mock with a polling-driven live tail and a lazily-fetched per-call detail view, matching the existing UI contract.
5. **Rolling metrics** — compute the four LLM Infra stat cards (Calls 24h, Avg Latency, Error Rate, Batched %) from the persisted log.
6. **Non-intrusive & configurable** — capture must never block or fail an LLM call; retention defaults to 28 days and is configurable; tracking has its own enable flag.

## Architecture

```
                          pipeline stage entry sets LLMCallContext (contextvars)
                                        │ origin / purpose / stage
                                        ▼
 call site ── LLMProvider method ── record_plugboard_call(system, input, result_extractor)
                                        │ builds enriched PlugboardCallRecord
                                        ▼
                                  _plugboard_sink (sync, fan-out)
                              ┌─────────────┴───────────────┐
                              ▼                              ▼
                    UsageAggregator + Prometheus    asyncio.Queue (bounded)
                    (unchanged, ops view)                   │
                                                            ▼
                                              _llm_writer_loop (async task)
                                                            │ batched INSERT
                                                            ▼
                                                  llm_calls table (Postgres)
                                                            ▲
   memory subservice (separate process) ── wrapped Graphiti client ──┘ (own asyncpg → workbench DSN)
                                                            │
   GET /api/llm/calls  ·  /api/llm/calls/{id}  ·  /api/llm/metrics  ──► useLLM hooks ──► LLMInfra tab
```

Data flows from each LLM call through the single `record_plugboard_call` instrumentation seam, which is enriched with ambient provenance (contextvars) and message bodies. The synchronous sink fans out to the existing Prometheus path and to a bounded queue drained by an async writer that persists rows. The memory subservice, being a separate process on a separate database, wraps its Graphiti LLM client and writes full rows directly to the workbench-owned table via a configured workbench DSN. The UI reads the table over three polling endpoints.

## Capture Mechanism

### Provenance via contextvars

A new `LLMCallContext` carries `origin`, `purpose`, and `stage`. It is stored in a `ContextVar` and set with a context manager at each pipeline stage entry; `record_plugboard_call` reads the current value when constructing a record. This avoids threading a context parameter through every `LLMProvider` ABC method and call site (ADR 0056).

```python
# providers/llm/context.py
@dataclass(frozen=True)
class LLMCallContext:
    origin: str        # e.g. "fr_31", "triage", "queue_scorer", "memory_subservice"
    purpose: str       # e.g. "score · relevance + priority"
    stage: str         # one of the canonical stages (below)

_current: ContextVar[LLMCallContext | None] = ContextVar("llm_call_context", default=None)

@contextmanager
def llm_call_context(*, origin: str, purpose: str, stage: str): ...
def current_llm_call_context() -> LLMCallContext | None: ...
```

Context managers are entered at: `pipeline/extraction.py` (extract), `pipeline/filter.py` (filter), `pipeline/triage.py` (triage), `pipeline/scheduler.py` interpret sites (aggregate), and `providers/queue_scorer/llm.py` (scoring). `contextvars` are task-local, so concurrent pipeline workers do not cross-contaminate.

### Canonical stages

| Call site | Provider method | `stage` | `origin` |
|-----------|-----------------|---------|----------|
| `anthropic.extract` | `extract` | `extract` | `extract` |
| `queue_scorer/llm` | `score_urgency` / `_many` | `scoring` | `queue_scorer` |
| `anthropic.score_relevance` / `_many` | filter scoring | `filter` | filter-rule id or `filter` |
| `anthropic.generate_triage_card` | triage | `triage` | `triage` |
| `anthropic.interpret_triage_response` | response interpret | `aggregate` | `aggregate` |
| memory subservice (Graphiti) | episode ingestion | `memory` | `memory_subservice` |

`enricher` and `briefing` are reserved stage values (the UI defines them) but produce **no** rows today: enrichers do not call an LLM (they query the memory layer and the `gh` CLI) and the morning briefing is template-driven.

### Enriched record + sink fan-out

`PlugboardCallRecord` gains optional fields; `record_plugboard_call` gains `system_prompt`, `input_prompt`, and `result_extractor`:

```python
@dataclass
class PlugboardCallRecord:
    client: str; model: str
    input_tokens: int = 0; output_tokens: int = 0
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    latency_s: float = 0.0; error_type: str | None = None; item_count: int = 1
    # NEW (optional; ignored by Prometheus, consumed by the DB writer):
    context: LLMCallContext | None = None
    system_prompt: str | None = None
    input_prompt: str | None = None
    completion: str | None = None
    structured: dict | None = None
    subcalls: list[dict] | None = None      # per-item breakdown for batches
    temperature: float | None = None
    tokens_estimated: bool = False
    is_fallback: bool = False

async def record_plugboard_call(*, client, model, do_call, sink,
        item_count=1, system_prompt=None, input_prompt=None,
        result_extractor=None,   # (resp) -> (completion_text, structured, subcalls)
        temperature=None, is_fallback=False) -> Any: ...
```

On success it reads `resp.usage` (as today) and, when `result_extractor` is provided, also extracts `completion`/`structured`/`subcalls` from `resp.content`. It attaches `current_llm_call_context()`. The existing Prometheus/`UsageAggregator` sink ignores the new fields.

`_plugboard_sink` fans out: (1) the existing `UsageAggregator.record` + Prometheus increments, **executed only when `config.metrics.enabled`**; (2) `queue.put_nowait(rec)` onto a **bounded** `asyncio.Queue` (maxsize 1000), **executed only when `config.llm_tracking.enabled and stores.llm_calls is not None`**. A new `_llm_writer_loop` task drains the queue and batch-inserts via `stores.llm_calls.save_many(...)`. On `QueueFull` or any writer/DB error, the record is logged and dropped — the LLM call is never blocked or failed (ADR 0057). **The sink closure and its wiring onto the providers (`inner_llm._sink`, `queue_scorer._sink`) are created whenever `config.metrics.enabled or config.llm_tracking.enabled` — not solely under `metrics.enabled` as today — so tracking works with `metrics.enabled=false` (decision d14). When `metrics.enabled=false`, `UsageAggregator`/Prometheus objects are not constructed and the Prometheus branch is skipped; when `llm_tracking.enabled=false` or `stores.llm_calls is None`, the queue is not created and the enqueue branch is skipped.** The writer task lifecycle mirrors `_summary_loop` (created in lifespan, cancelled on shutdown) and is gated on `llm_tracking.enabled`.

### Batch and structured-output capture

For batched paths (`anthropic._score_relevance_chunk`, `queue_scorer._score_urgency_chunk`), per-item subcalls are assembled inside the chunk method after parsing, where both the indexed input payload and the parsed JSON-array response are in scope:

- per-item `prompt` = the indexed input slice for that item (exact)
- per-item `completion` / `structured` = the parsed array element for that index (exact)
- per-item `tokens_in` / `tokens_out` = proportional split of the batch `resp.usage` by character share → row and subcalls marked `tokens_estimated = true`

`structured` stores the JSON the pipeline already extracts (`_extract_json`) for JSON-in-text calls, and the tool-result input for `interpret_triage_response` (tool-use); `completion` stores the raw response text.

**Batch parse-failure fallback:** when a batch index is malformed, `_score_relevance_chunk` re-invokes the single `score_relevance` (a second `record_plugboard_call`). These fallback single calls are emitted as their **own** rows with `is_fallback = true`; the batch row keeps only successfully-parsed indices in `subcalls`. Token totals are therefore an **upper bound** under fallback; aggregations may exclude `is_fallback` rows. This is documented, not silently corrected.

### Status

Rows are written only after a call returns, so persisted `status` ∈ `{ok, error}`. `running` is never persisted; the DB-backed tail shows completed calls streaming in. The UI is already null-tolerant and does not depend on `running` (ADR 0061).

## Memory Subservice Capture (full fidelity)

The memory subservice (`src/memory/`) is a separate process on a separate database whose LLM calls are owned by Graphiti via a wrapped `AnthropicClient`. To capture at full fidelity (user decision):

- Extend the existing client wrapper (`src/memory/.../llm.py` + `instrumentation.py`) to capture the system + input prompt, completion, structured result, and tokens (best-effort; when Graphiti does not surface `usage`, set `tokens_estimated = true`).
- The memory process writes **full rows directly to the workbench-owned `llm_calls` table** via its own `asyncpg` pool using a **configured workbench Postgres DSN** (memory otherwise uses a separate DB). `origin = "memory_subservice"`, `stage = "memory"`.
- Workbench is the sole schema owner (migration 013); memory is an INSERT-only writer pinned to a documented column contract (ADR 0059).
- Rollout (ADR 0053 cross-repo protocol): migration 013 is applied to the workbench DB **before** the memory writer deploys; the memory writer is behind an off-by-default flag with a table-presence preflight check.
- Memory keeps its existing Prometheus emission; the DB row is additive (no double count, since the UI reads the table and ops reads Prometheus).

## Data Model

One row per logical LLM call (a batch is one row); per-item subcalls nested in JSONB. Single-call cases are stored as `subcalls = [{one}]` for a uniform read path.

```sql
CREATE TABLE llm_calls (
    id                 BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    started_at         TIMESTAMPTZ NOT NULL,                 -- call start (UI `ts`)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),   -- row insert (retention anchor)
    origin             TEXT NOT NULL,
    purpose            TEXT NOT NULL,
    stage              TEXT NOT NULL,                        -- canonical stage value
    model              TEXT NOT NULL,
    temperature        DOUBLE PRECISION,
    status             TEXT NOT NULL,                        -- 'ok' | 'error'
    error_type         TEXT,
    batch              INTEGER NOT NULL DEFAULT 1,
    items              JSONB NOT NULL DEFAULT '[]',          -- string[]
    tokens_in          INTEGER NOT NULL DEFAULT 0,
    tokens_out         INTEGER,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms         INTEGER,
    system_prompt      TEXT,
    subcalls           JSONB NOT NULL DEFAULT '[]',          -- {item,prompt,completion,structured,tokens_in,tokens_out}[]
    tokens_estimated   BOOLEAN NOT NULL DEFAULT false,
    is_fallback        BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX idx_llm_calls_started_at ON llm_calls (started_at DESC);
CREATE INDEX idx_llm_calls_stage_started ON llm_calls (stage, started_at DESC);
```

Conventions followed: `TIMESTAMPTZ` (UTC), JSONB round-trip via `$N::jsonb` + `json.dumps`/`json.loads`, enum-like columns as `TEXT` (written via `.value`), BIGINT identity PK. No raw-body size cap (store raw, single-user); an optional `retention.llm_calls_max_rows` row-cap sweep is available but off by default.

### Domain models (`domain/llm_calls.py`)

```python
class LlmSubcall(BaseModel):
    item: str; prompt: str; completion: str
    structured: dict | None = None
    tokens_in: int; tokens_out: int | None = None

class LlmCallRecord(BaseModel):
    id: int | None = None
    started_at: datetime
    origin: str; purpose: str
    stage: Literal["extract","scoring","filter","triage","aggregate","enricher","briefing","memory"]
    model: str; temperature: float | None = None
    status: Literal["ok","error"]; error_type: str | None = None
    batch: int = 1; items: list[str] = Field(default_factory=list)
    tokens_in: int = 0; tokens_out: int | None = None
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    latency_ms: int | None = None
    system_prompt: str | None = None
    subcalls: list[LlmSubcall] = Field(default_factory=list)
    tokens_estimated: bool = False; is_fallback: bool = False
```

### Repository (`storage/base.py` + `storage/postgres/llm_calls.py`)

```python
class LlmCallStore(ABC):
    async def save_many(self, records: list[LlmCallRecord]) -> None: ...
    async def list_calls(self, *, limit: int, before: tuple[datetime,int] | None = None,
                         stage: str | None = None, status: str | None = None,
                         origin: str | None = None, q: str | None = None) -> list[LlmCallRecord]: ...
    async def get_by_id(self, call_id: int) -> LlmCallRecord | None: ...
    async def count_since(self, since: datetime) -> int: ...
    async def metrics_24h(self) -> dict: ...                 # calls/avg latency/error rate/batched
    async def delete_older_than(self, days: int) -> int: ...
    async def prune_to_max_rows(self, max_rows: int) -> int: ...
```

`PgLlmCallStore(pool)` is added to `Stores` as keyword-only optional `llm_calls: LlmCallStore | None = None` and constructed in `create_postgres_stores`. `save_many` batch-inserts; `list_calls` uses keyset (`before = (started_at, id)`) pagination ordered `started_at DESC, id DESC`.

## API

New router `api/llm.py`, prefix `/api/llm`, registered in `runtime/app.py` (import block + include loop); global bearer auth applies; a `503` guard fires if `stores.llm_calls is None`. Responses are bare dicts/lists (house convention); a route-level `_llm_call_view(record)` maps domain names to the exact UI contract field names (the house bare-dict/no-`response_model` convention is kept as-is).

| Endpoint | Params | Returns |
|----------|--------|---------|
| `GET /api/llm/calls` | `limit=Query(50,ge=1,le=200)`, `before` (cursor `ts,id`), `stage?`, `status?`, `origin?`, `q?` | bare list of `LLMCall` (summary only — no bodies) |
| `GET /api/llm/calls/{id}` | — | `{sysPrompt, subcalls[]}` (full bodies); `404` if unknown |
| `GET /api/llm/metrics` | — | `{calls_24h, avg_latency_ms, error_rate, batched_pct, window_hours: 24, as_of}` |

`LLMCall` view fields (exact UI names): `id` (rendered `f"llm_{id}"`), `ts` (= `started_at.isoformat()`), `origin`, `purpose`, `stage`, `model`, `temperature` (coalesced to a concrete number — `record.temperature or 0.0` — because the UI `LLMCall.temperature` type is non-null `number`), `status`, `batch`, `items`, `tokens_in`, `tokens_out`, `latency_ms`. List rows omit prompt/completion bodies; the detail endpoint returns them. `GET /api/llm/calls/{id}` accepts the rendered string id, strips the `llm_` prefix and parses the remainder as `int`, returning `404` if the prefix is missing, the remainder is non-numeric, or no row matches. Metric definitions (rolling 24h UTC, computed in SQL):

- `calls_24h` = `COUNT(*)` of rows with `created_at >= now()-'24h'`
- `avg_latency_ms` = `AVG(latency_ms)` over `status='ok'` rows (null when none)
- `error_rate` = `COUNT(*) FILTER (status='error') / NULLIF(COUNT(*),0)`
- `batched_pct` = `COUNT(*) FILTER (batch>1) / NULLIF(COUNT(*),0)`

## UI

Transport is TanStack Query polling via `pollWhenVisible` (no SSE; ADR 0060). New hooks in `ui/src/hooks/useLLM.ts`:

```ts
useLLMCalls(params)      // ['llm','calls',params]  refetchInterval pollWhenVisible(5_000)
useLLMCallDetail(id)     // ['llm','call',id]       enabled: id != null  (lazy)
useLLMMetrics()          // ['llm','metrics']       refetchInterval pollWhenVisible(15_000)
```

`SystemStatus.tsx` changes: remove `buildDefaultLLMCalls()` and the `setInterval`; pass real data into `<LLMInfra pool={...} />`; metrics cards read `useLLMMetrics()`; the detail dialog reads `useLLMCallDetail(id)` on row click. Live search (`q`) filters the already-fetched newest-N client-side (server `q` is reserved for scrollback). `LLM_STAGE_TONE` is extended with `extract`, `scoring`, and `memory` (additive; an unknown stage degrades to the default cyan, no crash). The inline `LLMInfra` table is kept (not generalized into `LiveTail`). All five UI states (loading/error/empty/unauthorized/degraded) are honored: `401`→unauthorized, `503`→error/degraded, empty→existing "no matching LLM calls".

## Telemetry

Additive. The existing `plugboard_*` Prometheus families and the `llm_usage_summary` log line are unchanged and remain the ops view; the `llm_calls` table is the queryable per-call log and the UI source of truth. A low-cardinality `stage` label may be added to `plugboard_*`; high-cardinality fields (`origin`, item ids) live only in the table. The two sinks are computed over different windows (Prometheus cumulative; table rolling 24h) and are not expected to match exactly (ADR 0058 note). Legacy per-method `llm_*` metrics are left as-is.

## Configuration

```python
class RetentionConfig(BaseModel):
    ...
    llm_calls_days: int = 28
    llm_calls_max_rows: int | None = None   # optional safety cap, off by default

class LlmTrackingConfig(BaseModel):
    enabled: bool = True

# AppConfig gains: llm_tracking: LlmTrackingConfig = Field(default_factory=LlmTrackingConfig)
```

Config is DB-authoritative (ADR 0055); these are pure pydantic additions with defaults, so absent keys fall back to defaults with no migration/backfill. Retention is swept daily by `run_retention_cleanup` (piggybacked on the morning briefing) — one added line: `results["llm_calls"] = await stores.llm_calls.delete_older_than(config.llm_calls_days)` plus an optional `prune_to_max_rows` call.

## File Changes

### New files
| File | Description |
|------|-------------|
| `src/workbench/providers/llm/context.py` | `LLMCallContext`, `llm_call_context()` contextmanager, `current_llm_call_context()` |
| `src/workbench/domain/llm_calls.py` | `LlmCallRecord`, `LlmSubcall` pydantic models |
| `src/workbench/storage/postgres/llm_calls.py` | `PgLlmCallStore` |
| `src/workbench/migrations/versions/013_llm_calls.py` | `llm_calls` table + indexes |
| `src/workbench/api/llm.py` | `/api/llm/calls`, `/api/llm/calls/{id}`, `/api/llm/metrics` + `_llm_call_view` |
| `ui/src/hooks/useLLM.ts` | `useLLMCalls`, `useLLMCallDetail`, `useLLMMetrics` |
| `tests/test_llm_calls_store.py` | repository unit tests |
| `tests/test_llm_capture.py` | `record_plugboard_call` enrichment + sink/writer tests |
| `tests/test_llm_api.py` | API route + view-mapping + metrics tests |

### Modified files
| File | Description |
|------|-------------|
| `src/workbench/providers/llm/plugboard.py` | enrich `PlugboardCallRecord`; extend `record_plugboard_call` |
| `src/workbench/providers/llm/anthropic.py` | pass system/input prompt + `result_extractor` + per-item subcalls at each call site; `is_fallback` on fallback |
| `src/workbench/providers/queue_scorer/llm.py` | same enrichment for scoring + batch subcalls |
| `src/workbench/pipeline/{extraction,filter,triage}.py`, `pipeline/scheduler.py` | enter `llm_call_context(...)` at each stage |
| `src/workbench/runtime/app.py` | sink fan-out to bounded queue; `_llm_writer_loop` task; register `llm.router`; gate on `llm_tracking.enabled` |
| `src/workbench/storage/base.py` | `LlmCallStore` ABC + `Stores.llm_calls` keyword-only field |
| `src/workbench/storage/postgres/stores.py` | construct `PgLlmCallStore` |
| `src/workbench/storage/postgres/README.md` | document `llm_calls.py` (ADR 0054) |
| `src/workbench/config/models.py` | `RetentionConfig.llm_calls_days`/`max_rows`; `LlmTrackingConfig`; wire on `AppConfig` |
| `src/workbench/pipeline/scheduler.py` | add `llm_calls` to `run_retention_cleanup` |
| `ui/src/pages/SystemStatus.tsx` | remove mock; wire hooks; extend `LLM_STAGE_TONE` |
| `CONTEXT.md` | add glossary entries (applied during planning): LLM Call Context, `llm_calls` (durable per-call log), Subcall, `tokens_estimated`, `is_fallback`, two-sink model |
| memory repo: `src/memory/.../llm.py`, `instrumentation.py`, config, writer | wrap Graphiti client; write full rows to workbench DSN; off-by-default flag + preflight |

## Verification

This is done when:
1. A real pipeline run (extract → score → filter → triage → interpret) produces `llm_calls` rows with correct `stage`/`origin`, non-null `system_prompt`, `subcalls`, tokens, and latency.
2. A batched relevance/scoring call produces one row with `batch=N`, `items` of length N, and N `subcalls` (each with its own prompt/completion/structured); the row is `tokens_estimated=true`.
3. A forced batch parse failure produces the batch row plus `is_fallback=true` single rows, with no crash and no lost call.
4. Killing Postgres mid-run does not block or fail any LLM call; the writer logs dropped records and recovers when Postgres returns.
5. `GET /api/llm/calls` returns newest-N summaries (no bodies); `GET /api/llm/calls/{id}` returns `{sysPrompt, subcalls}`; `GET /api/llm/metrics` returns the four values matching SQL over the last 24h; all require auth and `503` when the store is unconfigured.
6. The LLM Infra tab shows real calls streaming in (polling), search filters live rows, clicking a row opens real prompt/completion/structured output, and all five UI states render.
7. Memory subservice LLM calls appear as `origin=memory_subservice, stage=memory` rows with captured bodies (tokens `tokens_estimated=true` when Graphiti omits usage); migration 013 is applied before the memory writer is enabled.
8. Records older than `retention.llm_calls_days` (default 28) are deleted by the daily sweep; `llm_tracking.enabled=false` disables persistence with no other behavior change.
9. `make migrate` applies `013` and `python -m pytest` (or the project test command) passes including the new tests; `npx tsc -b` and the UI tests pass.

## Resolved Questions

1. **Capture fidelity:** → Full (bodies + context). Threaded via contextvars + extended `record_plugboard_call`. [user]
2. **Prompt/completion storage:** → Store raw, no scrubbing (single-user platform). [user]
3. **Retention:** → Configurable, default 28 days; daily sweep via `run_retention_cleanup`; optional row-cap. [user + research]
4. **Capture scope:** → Everything that calls an LLM: main LLM (extract/filter/triage/aggregate), queue scorer (scoring), and memory subservice (memory) at full fidelity; enrichers/briefing do not call LLMs. [user + research]
5. **Memory subservice:** → Full fidelity by wrapping Graphiti's client; writes full rows to the workbench-owned table via a configured workbench DSN. [user]
6. **Row granularity:** → One row per call; per-item `subcalls` nested in JSONB; single calls stored as one subcall. [grilling]
7. **`running` status:** → Never persisted; tail shows completed `ok`/`error` rows; UI is null-tolerant so nothing breaks. [research Q7]
8. **Provenance mechanism:** → `contextvars` `LLMCallContext`, not interface-parameter threading. [ADR 0056]
9. **Sync→async write:** → Sink fans out to a bounded queue drained by `_llm_writer_loop`; errors dropped, never block the call. [ADR 0057]
10. **Per-item tokens in a batch:** → Proportional split, flagged `tokens_estimated`; prompts/completions/structured per item are exact. [grilling]
11. **Batch fallback double-count:** → Fallback single calls are separate `is_fallback` rows; totals are an upper bound, documented. [research Q4]
12. **Stat-card source:** → SQL aggregates over `llm_calls` (24h rolling UTC), not Prometheus. [grilling]
13. **Transport:** → TanStack polling (`pollWhenVisible`), no SSE. [research + ADR 0060]
14. **Detail payload:** → Fetched lazily on click; list rows carry summaries only. [grilling]
15. **Stages added to UI:** → `extract`, `scoring`, `memory` added to `LLM_STAGE_TONE` (additive; graceful degrade). [research]
16. **Gating:** → New `llm_tracking.enabled` (default true), independent of `metrics.enabled`. [grilling]
17. **Telemetry relationship:** → Additive; table is UI/source-of-truth, Prometheus stays for ops. [ADR 0058]
18. **API typing:** → Keep bare dicts + hand-written TS interfaces (no `response_model`). [house convention]

## Out of Scope

- An in-flight (`running`) call registry / streaming transport (SSE/WebSocket).
- Scrollback UX beyond the live newest-N (the `before` cursor + server `q` are specified but the dedicated history-browse UI is deferred).
- Deprecating or refactoring the legacy per-method `llm_*` Prometheus metrics.
- Generalizing `LiveTail` into a shared column-configurable component.
- Capturing non-LLM external calls (the `gh` CLI in the GitHub enricher).
- A 5th "cache tokens" stat card (cache tokens are stored but not surfaced).
