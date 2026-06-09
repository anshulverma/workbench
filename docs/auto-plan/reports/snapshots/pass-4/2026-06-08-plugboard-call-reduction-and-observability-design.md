# Design Spec: Plugboard Call Reduction & Observability

**Status:** Draft — 2026-06-08
**Domains:** backend, observability, devops, data-ml
**Related ADRs:** 0048 (unit-of-work batching), 0049 (two-layer LLM instrumentation + sink injection), 0050 (memory-service Graphiti client instrumentation + unified `plugboard_*` family), 0051 (unauthenticated `/metrics` on both services)

## 1. Problem & Goal

Workbench is a Meta-internal, single-user, low-volume intelligence feed. Three clients call the Meta LLM gateway ("plugboard", `https://plugboard.x2p.facebook.net`):

| Client | Code | Model | Per-item fan-out |
|---|---|---|---|
| `main_llm` | `AnthropicLLM` (`MetaAnthropicLLM`) | Sonnet | `extract` (1/raw item) → `score_relevance` (1/extracted item) → `generate_card` (1/triaged item) |
| `queue_scorer` | `LLMQueueScorer` (`MetaQueueScorer`) | Haiku | `score_urgency` (1/raw item at enqueue, if urgency_signals) |
| `memory` | Graphiti via `MetaMemoryLLMClient` (separate process) | Haiku | `add_episode` per recorded decision/triage → **many** Haiku calls (entity/edge extraction, dedup, temporal resolution) |

One source poll of N items becomes hundreds of plugboard calls; the memory layer is the largest amplifier and `auto_drop` items needlessly generate episodes.

**Goals (this work):**
1. **Reduce** plugboard calls: (a) config-gate `auto_drop` memory recording; (b) batch non-interactive same-type calls within their natural unit of work.
2. **Observe** plugboard calls: Prometheus metrics (calls, tokens, latency, errors by `client`+`model`) on two `/metrics` endpoints (main app + memory service) + a periodic batched structured-log summary. Grafana plugs in later.

**Non-goals (flagged, not implemented):** curated Grafana dashboards (later); resolving the Meta read-only-config-mount vs hot-reload-write-back conflict; an Anthropic Message Batches (async) path.

## 2. What already exists (extend, don't rebuild)

- `src/workbench/metrics.py` — `WorkbenchMetrics` dataclass + `create_metrics(registry=None)`. LLM metrics today: `llm_calls{method}`, `llm_call_seconds{method}`, `llm_errors{method,error_type}` — **no model/client label, no token counters**.
- `src/workbench/instrumentation.py` — `InstrumentedLLMProvider(inner, metrics)` decorates the provider **interface methods** (method-view, latency-by-method). It wraps the coroutine *result* (domain objects), so it **cannot see tokens/model**.
- `src/workbench/main.py` — `/metrics` endpoint already present and **unauthenticated**; `prometheus-client>=0.20` already a dep; `app.state.metrics = create_metrics()`; `app.state.llm` wrapped with `InstrumentedLLMProvider`. **Gap:** `app.state.queue_scorer` is not wrapped.
- `config.py` — `MetricsConfig(enabled=True, endpoint="/metrics")` and `DebugConfig(llm_token_usage=True, ...)` already exist (the token path was never populated).
- Memory service (`src/memory/memory/`) — separate FastAPI app; **no `/metrics`, no `prometheus-client` dep** (net-new). Restart-only (no hot-reload). Has its own structlog setup + lifespan + ingestion worker.

## 3. Decisions

### 3.1 auto_drop config gate (ADR-free; trivially reversible)
- New field: `pipeline.record_drop_decisions: bool = False` (in `PipelineConfig`, beside the include/drop thresholds).
- `PipelineEngine.__init__` gains `record_drop_decisions: bool = False`; lifespan passes `config.pipeline.record_drop_decisions`. **Also wire `triage_expiry_days=config.triage.expiry_days`** (currently omitted → silently defaults to 7; in-scope cleanup).
- `engine.py` `auto_drop` branch: wrap the `record_pipeline_decision(...)` call in `if self.record_drop_decisions:`. The `job.items_dropped += 1` / `update_job` stays **outside** the gate (job accounting must be unaffected).
- `auto_include` recording is **unchanged** (positive training signal for the preference learner).
- When memory is `NoopMemoryLayer` (OSS default) the gate is a harmless no-op; its value is in the Meta `HttpMemoryLayer` path (suppresses the HTTP POST + downstream Graphiti fan-out).

### 3.2 Unit-of-work batching (ADR 0048)
- **Mechanism:** NOT a time-window micro-batcher. `score_relevance` is awaited serially in a for-loop inside `process_raw_item`. `score_urgency` is awaited inside `PipelineEngine.enqueue` (the `if self.queue_scorer and urgency_signals:` branch), called once per raw item by the scheduler from BOTH enqueue paths (`_poll_one_source` non-monitoring branch AND `_route_poll_results` for monitoring-capable sources). The fan-out is statically known at the call site, so collapse it directly. No background flush task, no wait window, no added latency.
- New provider methods:
  - `score_relevance_many(items, preference_facts, rules) -> list[(relevance:int, confidence:int)]` — refactor `process_raw_item`'s score loop to one call over all extracted items of a raw item.
  - `score_urgency_many(items: list[tuple[str, dict]]) -> list[int]` — score all new raw items of one poll in one call. **Requires raising the scorer `max_tokens`** (currently 100, too small for N results): `max_tokens = min(4096, 40 * len(items) + 100)` (safe against truncation at `max_batch_size=20`).
- **Urgency call-site move:** because `score_urgency` lives inside `enqueue` today, hoist it out — add `PipelineEngine.enqueue_prescored(...)` (or an explicit `urgency_score` param to `enqueue`) so the scheduler pre-scores the un-processed raw items of a poll once via `score_urgency_many`, then enqueues each with its precomputed score (no second per-item scorer call). Both scheduler enqueue paths use the pre-scored path; in `_route_poll_results` the new-item subset is pre-scored before the per-item change-detection loop. Only items carrying `urgency_signals` are scored; others default to 50 (current behavior). When `batching.score_urgency=false`, fall back to per-item `enqueue` (scorer called inside `enqueue` as today).
- **Multi-item prompt:** input is a JSON array, each element carrying an explicit integer `index`; model returns a JSON array echoing each `index`; parse by matching on index (not position). Validate every expected index is present.
- **Fallback (preserve correctness floor):** transport/parse failure of the whole batch → existing `_call_with_retry` 3× exp-backoff on the batch prompt; after exhaustion OR for any missing/malformed sub-result → fall back to the existing **per-item** method (each with its own retry). No split-and-retry.
- **Not batched:** `extract` (1/raw item, large inputs, cross-contamination risk) and `generate_triage_card` (user-facing personalized content). `interpret_triage_response` excluded (interactive).
- **Relevance routing:** `score_and_decide` (in `filter.py`) currently does per-item memory queries (preferences/entity/relationships) + filter-rule fetch + one `score_relevance`, then applies the threshold branch inline. Its threshold params already default to `70`/`30`/`70` but are **never wired from `PipelineConfig`** today (a dead-config latent bug, like `triage_expiry_days`). Extract that threshold branch into a **pure helper `decide_from_score(relevance, confidence, *, include_threshold=70, drop_threshold=30, confidence_threshold=70) -> str` in `filter.py`** (defaults present so callers may omit); `score_and_decide` calls it after `score_relevance`. **Wire the dead config (in-scope cleanup):** add `include_threshold`/`drop_threshold`/`confidence_threshold` params to `PipelineEngine.__init__` (defaulting 70/30/70), sourced in lifespan from `config.pipeline.*`, stored as `self.include_threshold` etc.; the engine passes them through to both `score_and_decide` and the precomputed-score path `filter.decide_from_score(relevance, confidence, include_threshold=self.include_threshold, drop_threshold=self.drop_threshold, confidence_threshold=self.confidence_threshold)`. No threshold constants are duplicated in `engine.py`; `PipelineConfig` becomes the real source. The batch refactor gathers per-item facts (via `asyncio.gather`), calls `score_relevance_many` once, then routes each item through the retained single-item helper `_process_extracted_item` (given the precomputed `(relevance, confidence)`, which calls `filter.decide_from_score` with the engine's configured thresholds instead of `score_and_decide`) so per-item auto_include/auto_drop/triage routing, per-item job counters, item commit, and the §3.1 drop-recording gate are all preserved.
- **Config:** new `batching:` section — `enabled: bool = true`, `score_relevance: bool = true`, `score_urgency: bool = true`, `max_batch_size: int = 20`. Read at each fan-out call site (hot-reload-safe, no background state). Large polls chunk into `max_batch_size`; empty extraction → no call; single item → degenerate batch of 1.

### 3.3 Two-layer LLM instrumentation (ADR 0049)
- **Call-site shim:** a free helper module `src/workbench/providers/_plugboard.py` wrapping `messages.create`. It is the only layer where `response.usage` (tokens), `self.model`, and the per-class `client` identity are all in scope. Called by `AnthropicLLM._call_with_retry`, `AnthropicLLM.interpret_triage_response`, and `LLMQueueScorer.score_urgency`. Meta subclasses inherit (they don't override these). Sits below `_call_with_retry`'s loop → counts each HTTP attempt (retries included).
- **Sink injection (no metrics import in providers):** base providers gain an optional `on_plugboard_call: Callable[[PlugboardCallRecord], None] | None = None` constructor param (default no-op). `PlugboardCallRecord` = dataclass(client, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, latency_s, error_type | None, item_count: int = 1). The workbench-side sink (wired in lifespan, closing over `app.state.metrics` + the usage aggregator) translates records into Prometheus increments. This preserves provider pluggability.
- **Both layers coexist:** keep the existing `InstrumentedLLMProvider` method-view decorator (latency-by-method) AND the new transport-view shim. Distinct metric names → no double counting. They intentionally disagree (retries inflate the shim's call count; batching folds items).
- **Queue scorer:** wire its sink in lifespan (currently entirely un-instrumented). No separate `InstrumentedQueueScorer` decorator needed — the shim covers calls/tokens/latency/errors; `score_urgency` is 1:1 with one create so call-site latency == method latency.

### 3.4 Metric schema (ADR 0049, 0050)
New `plugboard_*` family, **unified across both processes** (uniform Grafana queries; `client` label distinguishes role/process; Prometheus also adds `job`/`instance`):
- `plugboard_calls_total{client, model}` — Counter (HTTP attempts).
- `plugboard_call_seconds{client, model}` — Histogram (custom buckets up to ~60s; LLM calls exceed default 10s).
- `plugboard_tokens_total{client, model, direction}` — Counter; `direction ∈ {input, output, cache_read, cache_write}` (cache via defensive `getattr(usage, ..., 0)`).
- `plugboard_errors_total{client, model, error_type}` — Counter.
- `plugboard_items_total{client, model}` — Counter (logical items folded into calls; `rate(items)/rate(calls)` = batching win).
- `client ∈ {main_llm, queue_scorer, memory}`; `model = self.model`. All labels low-cardinality. The existing `llm_*{method}` decorator metrics are unchanged.

### 3.5 Memory-service instrumentation (ADR 0050)
- **Seam:** `InstrumentedAnthropicClient` subclass of Graphiti's `AnthropicClient` in **new** `src/memory/memory/instrumentation.py`, wired in `create_llm_client` (`src/memory/memory/llm.py`) by wrapping the returned `.client`. Covers both the OSS `DefaultLLMClient` and the Meta `MetaMemoryLLMClient` with **no workbench-meta change** (foundational/Meta split respected). Reject httpx hooks (OSS client builds its own internal httpx — no uniform seam) and reject layer-only (can't see Graphiti's internal fan-out).
- **Override target:** the method that issues `messages.create` (`generate_response`/`_generate_response`). Record **calls/latency/errors authoritatively**; **tokens best-effort** (if the pinned Graphiti version surfaces `usage`; else leave token counter unincremented, documented). The exact method name + usage availability is a **verification step** at implementation time (read the pinned `graphiti_core` source); design degrades gracefully either way.
- **Metrics:** emit the same `plugboard_*` family with `client="memory"` (chosen over a `memory_*` prefix for cross-process uniformity), PLUS episode-level `memory_episodes_ingested_total{type}` and reuse existing gauges (`memory_ingestion_queue_depth`, `memory_dead_letter_count`, `memory_connection_healthy{name}`). **`type` enum:** `triage|decision` are incremented in `_run_ingestion_worker` (per processed entry, keyed by `entry.type`). `entity` is incremented in the `record_entity` request handler (which calls `layer.record_entity` synchronously, bypassing the worker) — so covering `type=entity` requires instrumenting that handler, not just the worker. `operation` granularity (extract_nodes/edges/dedupe) is **not** attempted in v1 (Graphiti-version-fragile) — single implicit operation.
- **Wiring:** add `prometheus-client` to `src/memory/pyproject.toml`; create a memory-scoped registry in lifespan (`app.state.metrics`); add unauthenticated `/metrics` to `memory/main.py` `create_app()` (mirror main app, `include_in_schema=False`). The memory service applies no auth middleware today, so no exemption is needed. Edit **only** `src/memory/memory/`, never `src/memory/build/` or `build/lib/` (stale artifacts).
- **Config:** add a `MetricsConfig` (enabled=True, endpoint="/metrics", summary_log=True, summary_interval_seconds=30) section to `src/memory/memory/config.py` + `MemoryConfig`. Restart-only.

### 3.6 Periodic batched structured log (ADR-free)
- **Source:** a small in-process **usage aggregator** (plain dict keyed by `(client, model)` accumulating calls/errors/tokens) updated by the **same plugboard sink** that increments Prometheus (NOT by reading private `counter._value`). Resolves the token-availability problem — the sink sees tokens.
- **Delta semantics:** the aggregator exposes `drain()` returning counts-since-last and zeroing the live dict (single consumer). Prometheus counters stay cumulative; the log shows per-interval activity.
- **Task:** a background asyncio task wakes every `metrics.summary_interval_seconds` (default 30), drains, and emits ONE structlog line `llm_usage_summary` (fields: `process` ∈ {workbench, memory}, `interval_seconds`, per-(client,model) calls/errors/tokens). **Skip emission when empty** (don't compound existing log chatter). Gated by `metrics.summary_log` (default true).
- **Both processes:** each runs its own aggregator + task in its lifespan; cancel/await on shutdown (mirror worker/scheduler teardown), before provider teardown.
- **Privacy:** counts/tokens/labels only — no content/PII; passes `SanitizingProcessor` untouched.

### 3.7 Config gating semantics (ADR-free)
- `metrics.enabled=False` → sink is no-op + `/metrics` returns empty/404; token capture is skipped (no metrics to feed).
- `metrics.summary_log=False` → no periodic summary task.
- `DebugConfig.llm_token_usage` → gates **verbose per-call** token logging only (distinct from the summary; this finally gives that existing-but-unused flag a behavior). Counter increments are unconditional when `metrics.enabled`.

### 3.8 /metrics auth (ADR 0051)
- Unauthenticated on **both** services. On the main app, this adds `/metrics` to the existing `BearerTokenMiddleware` exemption set as a deliberate second carve-out alongside `/health` (CLAUDE.md invariant). The **memory service applies no auth middleware at all today** — its `/metrics` is consistent with its existing fully-unauthenticated posture (no carve-out needed). Standard Prometheus scrape pattern.
- **Binding:** the main app binds loopback by default (`ServerConfig.host="127.0.0.1"`) + SSH tunnel. The **memory service binds `0.0.0.0`** (Dockerfile/compose `--host 0.0.0.0`; its `ServerConfig` has no `host` field), so under `network_mode: host` its `/metrics` is reachable on all host interfaces — no new exposure beyond its already-`0.0.0.0`-bound unauthenticated endpoints. The operative mitigation for the memory service is host-level network controls + non-PII low-cardinality data, NOT loopback.

### 3.9 Ops wiring (ADR-free)
- `prometheus.yml` at the **workbench repo root** (foundational; observability isn't Meta-specific): two static `localhost:8421` + `localhost:8422` targets (everything runs `network_mode: host`, so targets are localhost, not compose service names).
- Add `prometheus` + `grafana` services to the **foundational** `docker-compose.yml` (`network_mode: host`; mount `prometheus.yml:ro`; `./data/prometheus` + `./data/grafana` volumes). Grafana datasource (Prometheus) provisioned; one minimal starter dashboard JSON optional; curated dashboards deferred.
- Update example configs (`config.example.yml`, memory example config) with the new fields; Meta overlay (`config.meta.yml`, `memory-config.meta.yml`) only where it overrides. YAML stays source of truth.
- Docs: CONTEXT.md term additions (done); a foundational "Observability stack" run-doc; plugboard-specific framing in the Meta overlay per the doc-split preference.

## 4. Edge cases (consolidated)
- Empty extraction `[]` → no batched call. Single item → degenerate batch of 1. Large poll → chunk by `max_batch_size`. `score_urgency_many` output cap raised with batch size.
- Failed call before a response → count call + error, zero tokens. `interpret_triage_response` swallows its exception (returns fallback) → the shim still records a `plugboard_errors_total` (genuine gateway failure); the method-view decorator records success — this disagreement is correct.
- Memory: Graphiti call failures (max_retries=1) counted; episode producing 0 entities; `/metrics` before Graphiti init; never edit build artifacts.
- Tokens unavailable from Graphiti → calls/latency/errors only (documented best-effort).

## 5. Out-of-scope / flagged for the user
- **Read-only config mount vs hot-reload write-back** in the Meta container (`config.example.yml:/app/config.yml:ro`) — pre-existing conflict, unaffected by these restart-time flags, but contradicts the write-back preference. Needs a separate decision.
- **Curated Grafana dashboards** — deferred ("plug in later").
- **Anthropic Message Batches (async) API** — rejected for this iteration (adds pending-state to the durable queue).

## 6. Success criteria
- `auto_drop` items produce zero memory-recording calls when `record_drop_decisions=false` (test asserts `record_pipeline_decision` not called).
- `score_relevance` calls drop from N (one per extracted item of a raw item) to `ceil(num_extracted / max_batch_size)` per raw item. `score_urgency` calls drop from one-per-new-item to `ceil(num_signalled_new_items / max_batch_size)` **per enqueue path** — i.e. summed over the two paths (`_poll_one_source` non-monitoring branch and the new-item subset of `_route_poll_results`), not a single global "N to 1" per poll, because the two paths pre-score their own item subsets independently and only items carrying `urgency_signals` are scored at all. The aggregate win is measurable via `plugboard_items_total / plugboard_calls_total` for `client=main_llm` and `client=queue_scorer` (ratio > 1 confirms folding).
- Both `/metrics` endpoints expose `plugboard_*{client,model}` covering all three clients; tokens present for main_llm + queue_scorer (memory best-effort).
- `llm_usage_summary` emitted ≤ every `summary_interval_seconds`, skipped when idle.
- All existing tests pass; new tests cover the gate, the batch + fallback, and the shim accounting.
