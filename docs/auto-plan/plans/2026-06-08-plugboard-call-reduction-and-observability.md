# Plugboard Call Reduction & Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cut plugboard (Meta LLM gateway) call volume via config-gated drop-recording and unit-of-work batching, and make all plugboard calls observable via Prometheus + a periodic structured-log summary across both the main app and the memory service.

**Architecture:** Extend existing infra (`metrics.py`, `instrumentation.py`, `/metrics`, `prometheus-client`). A transport-view call-site shim around `messages.create` emits `PlugboardCallRecord`s to a constructor-injected sink that feeds both Prometheus (`plugboard_*{client,model}`) and an in-process usage aggregator drained by a periodic `llm_usage_summary` task. Batching collapses serial `score_relevance`/`score_urgency` fan-outs into `_many` calls. The memory service gets the same treatment via an `InstrumentedAnthropicClient` subclass of Graphiti's client.

**Tech Stack:** Python 3, FastAPI, asyncpg, anthropic SDK, prometheus-client, structlog, graphiti-core, pytest/pytest-asyncio, docker-compose (Podman, host networking).

**Test commands:**
- All: `make test` (i.e. `python -m pytest tests/ -v --tb=short`)
- Single: `python -m pytest tests/test_pipeline.py::test_name -v`
- Memory service: `python -m pytest src/memory/tests/ -v` (confirm path; else `cd src/memory && python -m pytest -v`)
- Lint: `make lint`

---

## File Structure

**Main app**
- `src/workbench/config.py` — Modify: add `pipeline.record_drop_decisions`; add `metrics.summary_log`, `metrics.summary_interval_seconds`; add `batching` section + `AppConfig.batching`.
- `src/workbench/pipeline/engine.py` — Modify: gate `auto_drop` recording; refactor score loop to `score_relevance_many`; pass `triage_expiry_days`.
- `src/workbench/pipeline/scheduler.py` — Modify: `_poll_one_source` uses `score_urgency_many`.
- `src/workbench/providers/_plugboard.py` — Create: `PlugboardCallRecord` + `record_plugboard_call(...)` async wrapper.
- `src/workbench/providers/llm/base.py`, `src/workbench/providers/queue_scorer/base.py` — Modify: add `on_plugboard_call` sink param to constructors (or to ProviderConfig handling).
- `src/workbench/providers/llm/anthropic.py` — Modify: route `messages.create` through the shim; add `score_relevance_many`; add `_generate_card_body` unchanged.
- `src/workbench/providers/queue_scorer/llm.py` — Modify: route through shim; add `score_urgency_many`; raise `max_tokens` for batch.
- `src/workbench/metrics.py` — Modify: add `plugboard_*` metrics.
- `src/workbench/usage_aggregator.py` — Create: in-process aggregator with `record()`/`drain()`.
- `src/workbench/instrumentation.py` — Modify: `InstrumentedLLMProvider` proxies `score_relevance_many`/`score_urgency_many` (method-view).
- `src/workbench/main.py` — Modify: build sink, wire into llm + queue_scorer, start/stop `llm_usage_summary` task.

**Memory service**
- `src/memory/pyproject.toml` — Modify: add `prometheus-client>=0.20`.
- `src/memory/memory/metrics.py` — Create: memory registry + `plugboard_*` (client="memory") + `memory_episodes_ingested_total`.
- `src/memory/memory/instrumentation.py` — Create: `InstrumentedAnthropicClient` + aggregator.
- `src/memory/memory/llm.py` — Modify: wrap returned client in `create_llm_client`.
- `src/memory/memory/config.py` — Modify: add `MetricsConfig`.
- `src/memory/memory/main.py` — Modify: registry on state, `/metrics`, episode metrics in worker, summary task in lifespan.

**Ops/docs**
- `prometheus.yml` — Create (repo root).
- `docker-compose.yml` — Modify: add prometheus + grafana services.
- `config.example.yml`, memory example config — Modify: new fields.
- `docs/observability.md` — Create: run-doc. `CONTEXT.md` — already updated.

---

## Task 1: auto_drop config gate

**Files:**
- Modify: `src/workbench/config.py`, `src/workbench/pipeline/engine.py`, `src/workbench/main.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`)
```python
@pytest.mark.asyncio
async def test_auto_drop_not_recorded_when_flag_false(stores):
    from unittest.mock import AsyncMock
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.models import ExtractedItem, ItemCategory, RawItem
    import workbench.pipeline.engine as eng

    mem = AsyncMock()
    llm = AsyncMock()
    engine = PipelineEngine(stores, mem, llm, StubEnricher(), record_drop_decisions=False)
    ext = ExtractedItem(summary="noise", category=ItemCategory.INFORMATIONAL,
                        source_context="", raw_item=RawItem(id="X1", source_type="email",
                        source_label="", raw_text="x"))
    # force auto_drop
    async def fake(*a, **k): return ("auto_drop", 10, 95)
    eng.score_and_decide = fake
    await engine._process_extracted_item(ext, job=None)
    mem.record_pipeline_decision.assert_not_called()

@pytest.mark.asyncio
async def test_auto_drop_recorded_when_flag_true(stores):
    from unittest.mock import AsyncMock
    from workbench.pipeline.engine import PipelineEngine
    from workbench.providers.enrichment.stub import StubEnricher
    from workbench.models import ExtractedItem, ItemCategory, RawItem
    import workbench.pipeline.engine as eng

    mem = AsyncMock()
    llm = AsyncMock()
    engine = PipelineEngine(stores, mem, llm, StubEnricher(), record_drop_decisions=True)
    ext = ExtractedItem(summary="noise", category=ItemCategory.INFORMATIONAL,
                        source_context="", raw_item=RawItem(id="X2", source_type="email",
                        source_label="", raw_text="x"))
    async def fake(*a, **k): return ("auto_drop", 10, 95)
    eng.score_and_decide = fake
    await engine._process_extracted_item(ext, job=None)
    mem.record_pipeline_decision.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_pipeline.py::test_auto_drop_not_recorded_when_flag_false -v`
Expected: `TypeError: __init__() got an unexpected keyword argument 'record_drop_decisions'`

- [ ] **Step 3: Write minimal implementation**
In `config.py` `PipelineConfig`, add: `record_drop_decisions: bool = False`.
In `engine.py` `PipelineEngine.__init__`, add param `record_drop_decisions: bool = False` and `self.record_drop_decisions = record_drop_decisions`.
In `engine.py` `_process_extracted_item`, the `auto_drop` branch — wrap only the `record_pipeline_decision` call:
```python
elif action == "auto_drop":
    if self.record_drop_decisions:
        await self.memory.record_pipeline_decision(
            Item(source_type=ext_item.raw_item.source_type, source_id=ext_item.raw_item.id,
                 summary=ext_item.summary, category=ext_item.category,
                 origin=ItemOrigin.AUTO_INCLUDED, priority=Priority.P3),
            "auto_drop", f"relevance={relevance}")
    if job:
        job.items_dropped += 1
        await self.stores.jobs.update_job(job)
```
In `main.py` lifespan `PipelineEngine(...)` call, add `record_drop_decisions=config.pipeline.record_drop_decisions,` and `triage_expiry_days=config.triage.expiry_days,`.

- [ ] **Step 4: Run tests to verify pass**
Run: `python -m pytest tests/test_pipeline.py -k auto_drop -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**
`git add -A && git commit -m "feat(pipeline): config-gate auto_drop memory recording (ADR 0048-prep) [plan T1]"`

---

## Task 2: Plugboard call-site shim + record + sink param

**Files:**
- Create: `src/workbench/providers/_plugboard.py`
- Modify: `src/workbench/providers/llm/base.py`, `src/workbench/providers/queue_scorer/base.py`
- Test: `tests/test_plugboard_shim.py`

- [ ] **Step 1: Write the failing test** (`tests/test_plugboard_shim.py`)
```python
import pytest
from types import SimpleNamespace
from workbench.providers._plugboard import PlugboardCallRecord, record_plugboard_call

@pytest.mark.asyncio
async def test_shim_records_success_with_tokens():
    seen = []
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    resp = SimpleNamespace(usage=usage, content=[SimpleNamespace(text="ok")])
    async def call(): return resp
    out = await record_plugboard_call(
        client="main_llm", model="m", item_count=3,
        sink=seen.append, do_call=call)
    assert out is resp
    rec = seen[0]
    assert isinstance(rec, PlugboardCallRecord)
    assert rec.client == "main_llm" and rec.model == "m"
    assert rec.input_tokens == 10 and rec.output_tokens == 5
    assert rec.item_count == 3 and rec.error_type is None

@pytest.mark.asyncio
async def test_shim_records_error_then_reraises():
    seen = []
    async def call(): raise ValueError("boom")
    with pytest.raises(ValueError):
        await record_plugboard_call(client="queue_scorer", model="h",
                                    sink=seen.append, do_call=call)
    assert seen[0].error_type == "ValueError" and seen[0].input_tokens == 0

@pytest.mark.asyncio
async def test_shim_noop_when_sink_none():
    resp = SimpleNamespace(usage=None, content=[])
    async def call(): return resp
    out = await record_plugboard_call(client="main_llm", model="m", sink=None, do_call=call)
    assert out is resp
```

- [ ] **Step 2: Run to verify fail**
Run: `python -m pytest tests/test_plugboard_shim.py -v`
Expected: `ModuleNotFoundError: No module named 'workbench.providers._plugboard'`

- [ ] **Step 3: Implement** (`src/workbench/providers/_plugboard.py`)
```python
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

@dataclass
class PlugboardCallRecord:
    client: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_s: float = 0.0
    error_type: str | None = None
    item_count: int = 1

PlugboardSink = Callable[[PlugboardCallRecord], None]

async def record_plugboard_call(
    *, client: str, model: str, do_call: Callable[[], Awaitable[Any]],
    sink: PlugboardSink | None, item_count: int = 1,
) -> Any:
    start = time.monotonic()
    try:
        resp = await do_call()
    except Exception as e:
        if sink is not None:
            sink(PlugboardCallRecord(client=client, model=model,
                latency_s=time.monotonic() - start,
                error_type=type(e).__name__, item_count=item_count))
        raise
    if sink is not None:
        usage = getattr(resp, "usage", None)
        sink(PlugboardCallRecord(
            client=client, model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            latency_s=time.monotonic() - start, item_count=item_count))
    return resp
```
In `llm/base.py` and `queue_scorer/base.py` ProviderConfig (or `__init__`), accept an optional `on_plugboard_call` sink stored as `self._sink = config.http_client and ...` — concretely: add `on_plugboard_call: Any = None` to each `ProviderConfig` (arbitrary_types_allowed already set) and store `self._sink = config.on_plugboard_call` in `AnthropicLLM.__init__` / `LLMQueueScorer.__init__`. Default None preserves current behavior.

- [ ] **Step 4: Run to verify pass**
Run: `python -m pytest tests/test_plugboard_shim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
`git add -A && git commit -m "feat(providers): plugboard call-site shim + injectable sink (ADR 0049) [plan T2]"`

---

## Task 3: Route LLM + scorer calls through the shim; add `plugboard_*` metrics; wire sink

**Files:**
- Modify: `src/workbench/providers/llm/anthropic.py`, `src/workbench/providers/queue_scorer/llm.py`, `src/workbench/metrics.py`, `src/workbench/main.py`
- Test: `tests/test_metrics.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Failing test** (`tests/test_metrics.py`, append)
```python
def test_plugboard_metrics_exist():
    from prometheus_client import CollectorRegistry
    from workbench.metrics import create_metrics
    m = create_metrics(CollectorRegistry())
    m.plugboard_calls.labels(client="main_llm", model="m").inc()
    m.plugboard_tokens.labels(client="main_llm", model="m", direction="input").inc(10)
    m.plugboard_items.labels(client="main_llm", model="m").inc(3)
    m.plugboard_errors.labels(client="main_llm", model="m", error_type="X").inc()
    m.plugboard_call_seconds.labels(client="main_llm", model="m").observe(0.5)
```

- [ ] **Step 2: Run to verify fail**
Run: `python -m pytest tests/test_metrics.py::test_plugboard_metrics_exist -v`
Expected: `AttributeError: 'WorkbenchMetrics' object has no attribute 'plugboard_calls'`

- [ ] **Step 3: Implement**
In `metrics.py`: add fields `plugboard_calls`, `plugboard_errors`, `plugboard_tokens`, `plugboard_items` (Counters) + `plugboard_call_seconds` (Histogram, buckets `(0.1,0.25,0.5,1,2,5,10,20,30,60)`); construct them in `create_metrics` with the label sets from spec §3.4.
In `anthropic.py`: replace each `self.client.messages.create(...)` with `await record_plugboard_call(client="main_llm", model=self.model, sink=self._sink, item_count=<n>, do_call=lambda: self.client.messages.create(...))`. For `_call_with_retry`, item_count defaults 1; the batched callers pass N.
In `queue_scorer/llm.py`: same with `client="queue_scorer"`.
In `main.py` lifespan: build a sink closure `def llm_sink(rec): translate rec → app.state.metrics.plugboard_* increments (+ feed aggregator in Task 4)`. Pass it into provider construction. Since `create_provider(config.llm)` builds the provider from YAML, add the sink via the provider's ProviderConfig — i.e. set `config.llm["on_plugboard_call"]=llm_sink` before `create_provider`, or set `provider._sink = llm_sink` post-construction (simpler; do post-construction on both `app.state.llm._inner` and `app.state.queue_scorer`). Gate all increments on `config.metrics.enabled`.

- [ ] **Step 4: Run tests**
Run: `python -m pytest tests/test_metrics.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
`git add -A && git commit -m "feat(metrics): plugboard_* family + route LLM/scorer through shim (ADR 0049) [plan T3]"`

---

## Task 4: Usage aggregator + periodic `llm_usage_summary` (main app)

**Files:**
- Create: `src/workbench/usage_aggregator.py`
- Modify: `src/workbench/config.py`, `src/workbench/main.py`
- Test: `tests/test_usage_aggregator.py`

- [ ] **Step 1: Failing test**
```python
from workbench.usage_aggregator import UsageAggregator
from workbench.providers._plugboard import PlugboardCallRecord

def test_aggregate_and_drain():
    agg = UsageAggregator()
    agg.record(PlugboardCallRecord(client="main_llm", model="m", input_tokens=10, output_tokens=2))
    agg.record(PlugboardCallRecord(client="main_llm", model="m", input_tokens=5, error_type="X"))
    snap = agg.drain()
    assert snap[("main_llm","m")]["calls"] == 2
    assert snap[("main_llm","m")]["errors"] == 1
    assert snap[("main_llm","m")]["input_tokens"] == 15
    assert agg.drain() == {}  # drained resets
```

- [ ] **Step 2: Run to verify fail** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `UsageAggregator` (dict keyed by `(client, model)`, `record()` accumulates calls/errors/input_tokens/output_tokens, `drain()` returns + clears). Add config fields `metrics.summary_log: bool = True`, `metrics.summary_interval_seconds: int = 30`. In `main.py`: instantiate `app.state.usage_agg = UsageAggregator()`; have the sink call `app.state.usage_agg.record(rec)` in addition to Prometheus; start `app.state.summary_task = asyncio.create_task(_summary_loop(...))` that sleeps `summary_interval_seconds`, drains, and if non-empty logs `logger.info("llm_usage_summary", process="workbench", interval_seconds=..., usage=snap)`; cancel/await it in shutdown before provider teardown; skip when `summary_log` false.

- [ ] **Step 4: Run** `python -m pytest tests/test_usage_aggregator.py -v` → PASS.

- [ ] **Step 5: Commit** `git commit -am "feat(observability): usage aggregator + llm_usage_summary task [plan T4]"`

---

## Task 5: Batching — `score_relevance_many` + engine refactor

**Files:**
- Modify: `src/workbench/providers/llm/anthropic.py`, `src/workbench/pipeline/engine.py`, `src/workbench/pipeline/filter.py`, `src/workbench/instrumentation.py`, `src/workbench/config.py`
- Test: `tests/test_batching.py`

- [ ] **Step 1: Failing test**
```python
import pytest
from unittest.mock import AsyncMock
from workbench.providers.llm.anthropic import AnthropicLLM
from workbench.models import ExtractedItem, ItemCategory, RawItem

def _item(s, sid):
    return ExtractedItem(summary=s, category=ItemCategory.ACTION_ITEM, source_context="",
        raw_item=RawItem(id=sid, source_type="email", source_label="", raw_text="x"))

@pytest.mark.asyncio
async def test_score_relevance_many_parses_indexed(monkeypatch):
    llm = AnthropicLLM(AnthropicLLM.ProviderConfig(api_key="k"))
    async def fake_call(prompt, **k):
        return '[{"index":0,"relevance":80,"confidence":90},{"index":1,"relevance":20,"confidence":85}]'
    monkeypatch.setattr(llm, "_call_with_retry", fake_call)
    out = await llm.score_relevance_many([_item("a","1"), _item("b","2")], [], [])
    assert out == [(80, 90), (20, 85)]

@pytest.mark.asyncio
async def test_score_relevance_many_falls_back_on_missing_index(monkeypatch):
    llm = AnthropicLLM(AnthropicLLM.ProviderConfig(api_key="k"))
    async def fake_batch(prompt, **k):
        return '[{"index":0,"relevance":80,"confidence":90}]'  # missing index 1
    monkeypatch.setattr(llm, "_call_with_retry", fake_batch)
    llm.score_relevance = AsyncMock(return_value=(50, 50))
    out = await llm.score_relevance_many([_item("a","1"), _item("b","2")], [], [])
    assert out[0] == (80, 90)
    assert out[1] == (50, 50)  # per-item fallback for missing index
    llm.score_relevance.assert_awaited_once()
```

- [ ] **Step 2: Run to verify fail** → `AttributeError: score_relevance_many`.

- [ ] **Step 3: Implement**
Add `batching` config section (`enabled=True, score_relevance=True, score_urgency=True, max_batch_size=20`) + `AppConfig.batching`.
Add `AnthropicLLM.score_relevance_many(items, preference_facts, rules)`: build a BATCH_SCORE_PROMPT with a JSON array of `{index, summary, source_type}`; instruct model to return a JSON array of `{index, relevance, confidence}`; call `_call_with_retry`; parse; for each expected index missing/malformed, call per-item `score_relevance` as fallback; chunk inputs by `max_batch_size`; `[]` → return `[]`. Instrument with `item_count=len(chunk)` via the shim (pass through `_call_with_retry`'s shim call — add an `item_count` param to `_call_with_retry`).
In `filter.py`, extract the threshold if/elif/else branch of `score_and_decide` into a pure helper `decide_from_score(relevance, confidence, *, include_threshold=70, drop_threshold=30, confidence_threshold=70) -> str` (defaults present); have `score_and_decide` call it after `score_relevance`, forwarding its own threshold params.
**Wire the dead `PipelineConfig` thresholds (in-scope cleanup):** add `include_threshold: int = 70, drop_threshold: int = 30, confidence_threshold: int = 70` params to `PipelineEngine.__init__` (store as `self.include_threshold` etc.); in `main.py` lifespan pass `include_threshold=config.pipeline.include_threshold, drop_threshold=config.pipeline.drop_threshold, confidence_threshold=config.pipeline.confidence_threshold`. (Today `score_and_decide` is called with default thresholds — `PipelineConfig.*_threshold` is never used; this wires it for real.)
In `engine.py` `process_raw_item`: replace the sequential score loop — gather per-item facts for all extracted items (via `asyncio.gather`), call `score_relevance_many` once, then route each item through the **retained** single-item helper `_process_extracted_item`, refactored to accept a precomputed `(relevance, confidence)` (and skip its own `score_and_decide` call when given one). When routing a precomputed score, call `filter.decide_from_score(relevance, confidence, include_threshold=self.include_threshold, drop_threshold=self.drop_threshold, confidence_threshold=self.confidence_threshold)` — engine threads its configured thresholds, no constants duplicated in `engine.py`. Keeping `_process_extracted_item` as the routing helper preserves per-item auto_include/auto_drop/triage routing, the §3.1 drop-gate, per-item commit + job counters, AND keeps Task 1's drop-gate test valid (it calls `_process_extracted_item` directly).
In `instrumentation.py`: add `score_relevance_many` passthrough on `InstrumentedLLMProvider` (method-view `llm_calls{method="score_relevance_many"}`).

- [ ] **Step 4: Run** `python -m pytest tests/test_batching.py tests/test_pipeline.py -v` → PASS.

- [ ] **Step 5: Commit** `git commit -am "feat(pipeline): batch score_relevance within raw-item unit of work (ADR 0048) [plan T5]"`

---

## Task 6: Batching — `score_urgency_many` + scheduler refactor + max_tokens fix

**Files:**
- Modify: `src/workbench/providers/queue_scorer/llm.py`, `src/workbench/pipeline/scheduler.py`, `src/workbench/pipeline/engine.py` (enqueue path)
- Test: `tests/test_batching.py`

- [ ] **Step 1: Failing test**
```python
@pytest.mark.asyncio
async def test_score_urgency_many(monkeypatch):
    from workbench.providers.queue_scorer.llm import LLMQueueScorer
    s = LLMQueueScorer(LLMQueueScorer.ProviderConfig(api_key="k"))
    async def fake(prompt, **k): return None
    # stub the create to return indexed urgencies
    class R:  # minimal anthropic-like response
        class C: text='[{"index":0,"urgency":70},{"index":1,"urgency":10}]'
        content=[C()]; usage=None
    s.client = type("X", (), {"messages": type("M",(),{"create": staticmethod(lambda **k: _aw(R()))})})()
    out = await s.score_urgency_many([("t1",{"a":1}), ("t2",{})])
    assert out == [70, 10]
```
(Add helper `async def _aw(v): return v`.)

- [ ] **Step 2: Run to verify fail** → `AttributeError: score_urgency_many`.

- [ ] **Step 3: Implement**
`LLMQueueScorer.score_urgency_many(items: list[tuple[str, dict]]) -> list[int]`: build a batch URGENCY prompt (JSON array `{index, signals, content[:2000]}`), `max_tokens = min(4096, 40 * len(items) + 100)` (raise the 100 cap proportional to batch — fixes the hard blocker), parse indexed results, per-item fallback to `score_urgency` for missing/malformed; chunk by `max_batch_size`. Route through the shim with `client="queue_scorer", item_count=len(chunk)`.
**Hoist urgency scoring out of `engine.enqueue`:** today `PipelineEngine.enqueue` calls `self.queue_scorer.score_urgency(...)` internally (engine.py). Add `PipelineEngine.enqueue_prescored(raw_text, source_type, *, source_id, urgency_signals, urgency_score, trigger)` that skips the internal scorer call and uses the passed `urgency_score`. Keep the old `enqueue` (per-item scoring) for the `batching.score_urgency=false` path and the manual `process.py` path (no urgency_signals).
In `scheduler.py`, refactor **both** enqueue paths:
  - `_poll_one_source` non-monitoring branch: collect `raw_items`, filter to those with `urgency_signals`, call `score_urgency_many` once for that subset (others default 50), then `enqueue_prescored` each with its precomputed score.
  - `_route_poll_results`: pre-score the **new-item subset** (existing is None AND has urgency_signals) via one `score_urgency_many` before the loop, then `enqueue_prescored` new items inside the loop; change-detection/update branches are unchanged.
When `config.batching.score_urgency` is false, both paths fall back to per-item `enqueue` (scorer called inside `enqueue` as today).

- [ ] **Step 4: Run** `python -m pytest tests/test_batching.py -v` and `make test` → PASS.

- [ ] **Step 5: Commit** `git commit -am "feat(scheduler): batch score_urgency per poll + raise scorer max_tokens (ADR 0048) [plan T6]"`

---

## Task 7: Memory service — metrics, Graphiti client instrumentation, /metrics, summary

**Files:**
- Modify: `src/memory/pyproject.toml`, `src/memory/memory/llm.py`, `src/memory/memory/config.py`, `src/memory/memory/main.py`
- Create: `src/memory/memory/metrics.py`, `src/memory/memory/instrumentation.py`
- Test: `src/memory/tests/test_memory_metrics.py` (confirm test dir)

- [ ] **Step 1: Failing test**
```python
def test_memory_metrics_exist():
    from prometheus_client import CollectorRegistry
    from memory.metrics import create_metrics
    m = create_metrics(CollectorRegistry())
    m.plugboard_calls.labels(client="memory", model="h").inc()
    m.episodes_ingested.labels(type="decision").inc()
```
And an instrumentation test wrapping a fake Graphiti client whose generate method returns a response with `usage`, asserting `plugboard_calls`/`plugboard_tokens` increment and the inner result passes through.

- [ ] **Step 2: Run to verify fail** → `ModuleNotFoundError: memory.metrics`.

- [ ] **Step 3: Implement**
Add `prometheus-client>=0.20` to `src/memory/pyproject.toml`.
`memory/metrics.py`: dataclass + `create_metrics(registry)` with `plugboard_calls{client,model}`, `plugboard_call_seconds{client,model}`, `plugboard_tokens{client,model,direction}`, `plugboard_errors{client,model,error_type}`, `episodes_ingested{type}`, gauges `ingestion_queue_depth`, `dead_letter_count`.
`memory/instrumentation.py`: `InstrumentedAnthropicClient(graphiti_client, metrics, model, sink)` subclassing Graphiti's `AnthropicClient` (import from `graphiti_core.llm_client.anthropic_client`); override the generate method — **VERIFY** the real method name and `usage` availability against the pinned `graphiti_core` version; record calls/latency/errors authoritatively, tokens best-effort (`getattr` guarded), then `await super().<method>(...)`. Provide a small `__getattr__` passthrough if delegating by composition instead of subclassing.
`memory/llm.py` `create_llm_client`: after resolving the inner client, return `InstrumentedAnthropicClient(inner, metrics, config.model, sink)` (pass metrics/sink in; thread them from lifespan). Covers OSS + Meta.
`memory/config.py`: add `MetricsConfig(enabled=True, endpoint="/metrics", summary_log=True, summary_interval_seconds=30)` + `MemoryConfig.metrics`.
`memory/main.py`: create registry `app.state.metrics = create_metrics()` + `app.state.usage_agg` in lifespan; add unauthenticated `/metrics` (mirror main app); increment `episodes_ingested{type}` for ALL THREE enum values across their two distinct code paths:
  - `type=triage` and `type=decision` — in `_run_ingestion_worker`'s `process(entry)`, keyed by `entry_type = entry.get("type", "triage")` (increment after `mark_completed`, per processed entry).
  - `type=entity` — in the `record_entity` **request handler** (`@app.post("/record/entity")`), which calls `layer.record_entity(...)` synchronously and **bypasses the worker entirely**; without instrumenting this handler, `type=entity` would never emit. Increment `app.state.metrics.episodes_ingested.labels(type="entity").inc()` after the successful `layer.record_entity(...)` call.
Start/stop `llm_usage_summary` task (process="memory") in lifespan; cancel/await it in shutdown after `worker_task` is cancelled and before `graphiti.close()` (mirror the existing worker teardown ordering). Edit only `src/memory/memory/`, NOT build dirs.

- [ ] **Step 4: Run** memory tests + `make test` → PASS. If `graphiti_core` isn't importable in the test env, gate the instrumentation test with `pytest.importorskip("graphiti_core")` and keep the metrics-module test unconditional.

- [ ] **Step 5: Commit** `git commit -am "feat(memory): plugboard metrics + Graphiti client instrumentation + /metrics (ADR 0050,0051) [plan T7]"`

---

## Task 8: Ops wiring + example configs + docs

**Files:**
- Create: `prometheus.yml`, `docs/observability.md`
- Modify: `docker-compose.yml`, `config.example.yml`, memory example config

- [ ] **Step 1 (no unit test — config/ops):** Add `prometheus.yml` (repo root):
```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: workbench
    static_configs: [{ targets: ["localhost:8421"] }]
  - job_name: memory
    static_configs: [{ targets: ["localhost:8422"] }]
```
- [ ] **Step 2:** Add `prometheus` + `grafana` services to `docker-compose.yml` (`network_mode: host`; prometheus mounts `./prometheus.yml:/etc/prometheus/prometheus.yml:ro` + `./data/prometheus:/prometheus`; grafana mounts `./data/grafana:/var/lib/grafana` + a provisioning dir with a Prometheus datasource pointing at `http://localhost:9090`). Defer curated dashboards.
- [ ] **Step 3:** Update `config.example.yml`: add `pipeline.record_drop_decisions: false`, a `metrics:` block (`enabled`, `endpoint`, `summary_log`, `summary_interval_seconds`), a `batching:` block. Update the memory example config with its `metrics:` block. Leave Meta overlay configs (`config.meta.yml`, `memory-config.meta.yml`) to override only where needed.
- [ ] **Step 4: Verify the stack boots**
Run: `make up` then `curl -s localhost:8421/metrics | grep plugboard_calls_total` and `curl -s localhost:8422/metrics | grep plugboard_calls_total`; confirm Prometheus targets up at `localhost:9090/targets`.
Expected: both endpoints serve `plugboard_*`; both targets UP.
- [ ] **Step 5: Docs + commit**
Write `docs/observability.md` (run the stack, what each metric means, how to read `items_total/calls_total` as the batching win, the read-only-config caveat, deferred-dashboards note). `CONTEXT.md` already updated.
`git add -A && git commit -m "feat(ops): prometheus+grafana compose, scrape config, example configs, observability docs [plan T8]"`

---

## Out-of-scope (flagged, not implemented)
- Read-only config mount (`config.example.yml:/app/config.yml:ro`) vs hot-reload write-back in the Meta container — pre-existing conflict; needs a separate decision.
- Curated Grafana dashboards (datasource provisioned; dashboards later).
- Anthropic Message Batches async API.

## Validation checklist (post-implementation)
- [ ] `make test` green; `make lint` clean.
- [ ] `record_drop_decisions=false` → no `record_pipeline_decision` for drops (test).
- [ ] `score_relevance`/`score_urgency` call counts drop (observe `plugboard_items_total / plugboard_calls_total > 1`).
- [ ] Both `/metrics` expose `plugboard_*{client,model}` for all three clients.
- [ ] `llm_usage_summary` emitted on interval, skipped when idle.
- [ ] Edited `src/memory/memory/`, not build artifacts.
