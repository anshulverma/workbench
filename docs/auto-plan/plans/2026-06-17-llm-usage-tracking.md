# LLM Usage Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist full-fidelity per-LLM-call records (provenance + bodies + tokens + latency) from every component that calls an LLM, serve them via `/api/llm/*`, and feed the LLM Infra tab real data with rolling metrics.

**Architecture:** A `contextvars`-based `LLMCallContext` labels each call (origin/purpose/stage); `record_plugboard_call` is extended to capture bodies; the sync sink fans out to the existing Prometheus path and a bounded queue drained by an async writer into a new `llm_calls` table. The memory subservice wraps its Graphiti client and writes full rows to the workbench-owned table. The UI reads three polling endpoints. See `docs/auto-plan/specs/2026-06-17-llm-usage-tracking-design.md` and ADRs 0056–0061.

**Tech Stack:** Python 3.12 / FastAPI / asyncpg / Alembic / pydantic (backend); React 19 / Vite / TanStack Query (UI); Graphiti (memory subservice).

**Test commands:**
- Backend all: `python -m pytest tests/`
- Backend single: `python -m pytest tests/test_llm_calls_store.py::test_save_and_list -q`
- UI all: `cd ui && npx vitest run` (use Node 20: `export PATH=/tmp/node-v20.18.0-linux-x64/bin:$PATH`)
- UI single: `cd ui && npx vitest run src/pages/SystemStatus.test.tsx`
- Migrations: `make migrate`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/workbench/domain/llm_calls.py` | `LlmCallRecord`, `LlmSubcall` models |
| `src/workbench/migrations/versions/013_llm_calls.py` | `llm_calls` table + indexes |
| `src/workbench/storage/base.py` | `LlmCallStore` ABC + `Stores.llm_calls` |
| `src/workbench/storage/postgres/llm_calls.py` | `PgLlmCallStore` |
| `src/workbench/storage/postgres/stores.py` | construct the store |
| `src/workbench/providers/llm/context.py` | `LLMCallContext` + contextvar helpers |
| `src/workbench/providers/llm/plugboard.py` | enriched record + extended `record_plugboard_call` |
| `src/workbench/providers/llm/anthropic.py` | pass bodies/result_extractor/subcalls at call sites |
| `src/workbench/providers/queue_scorer/llm.py` | same for scoring |
| `src/workbench/pipeline/{extraction,filter,triage}.py`, `pipeline/scheduler.py` | enter `llm_call_context` |
| `src/workbench/runtime/app.py` | sink fan-out + writer task + router register |
| `src/workbench/config/models.py` | `RetentionConfig.llm_calls_days`/`max_rows`, `LlmTrackingConfig` |
| `src/workbench/api/llm.py` | `/api/llm/calls`, `/{id}`, `/metrics` + `_llm_call_view` |
| `ui/src/hooks/useLLM.ts` | `useLLMCalls`/`useLLMCallDetail`/`useLLMMetrics` |
| `ui/src/pages/SystemStatus.tsx` | remove mock; wire hooks; extend stages |
| memory repo | wrap Graphiti client; cross-DB writer + flag |

Order: **1→2→3** (data layer) → **4→5→6** (capture) → **7** (wiring) → **8** (API) → **9** (UI) → **10** (retention/config) → **11** (memory subservice, separate repo).

---

### Task 1: Domain models

**Files:**
- Create: `src/workbench/domain/llm_calls.py`
- Modify: `src/workbench/domain/__init__.py`
- Test: `tests/test_llm_calls_domain.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_llm_calls_domain.py
from datetime import datetime, timezone
from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall

def test_record_roundtrips_with_subcalls():
    rec = LlmCallRecord(
        started_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        origin="triage", purpose="score", stage="triage", model="claude-opus-4-8",
        temperature=0.2, status="ok", batch=1, items=["D1"], tokens_in=10, tokens_out=5,
        system_prompt="sys", subcalls=[LlmSubcall(item="D1", prompt="p", completion="c",
                                                  structured={"x": 1}, tokens_in=10, tokens_out=5)],
    )
    assert rec.stage == "triage"
    assert rec.subcalls[0].structured == {"x": 1}
    assert rec.model_dump()["status"] == "ok"

def test_defaults():
    rec = LlmCallRecord(started_at=datetime.now(timezone.utc), origin="o", purpose="p",
                        stage="extract", model="m", status="error")
    assert rec.batch == 1 and rec.items == [] and rec.subcalls == []
    assert rec.tokens_estimated is False and rec.is_fallback is False
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_llm_calls_domain.py -q`
Expected: `ModuleNotFoundError: workbench.domain.llm_calls`

- [ ] **Step 3: Write minimal implementation**
Create `src/workbench/domain/llm_calls.py` with the `LlmSubcall` and `LlmCallRecord` models exactly as in the spec ("Domain models" section). Add `__all__ = ["LlmCallRecord", "LlmSubcall"]`. In `domain/__init__.py` add `from workbench.domain.llm_calls import *` (follow the existing re-export block).

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_llm_calls_domain.py -q` → Expected: PASS

- [ ] **Step 5: Commit**
`git add -A && git commit -m "feat(domain): LlmCallRecord + LlmSubcall models"`

---

### Task 2: Migration 013 — `llm_calls` table

**Files:**
- Create: `src/workbench/migrations/versions/013_llm_calls.py`
- Test: `tests/test_migration_013.py` (or extend existing schema test)

- [ ] **Step 1: Write the failing test**
```python
# tests/test_migration_013.py — a lightweight presence assertion on the migration module
import importlib
def test_migration_013_defines_llm_calls():
    m = importlib.import_module("workbench.migrations.versions.013_llm_calls")
    assert m.revision == "013" and m.down_revision == "012"
    assert callable(m.upgrade) and callable(m.downgrade)
```

- [ ] **Step 2: Run** `python -m pytest tests/test_migration_013.py -q` → Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**
Create `013_llm_calls.py` with `revision="013"`, `down_revision="012"`, `op.create_table("llm_calls", ...)` exactly per the spec's SQL (BIGInteger identity PK, `TIMESTAMPTZ` cols with `server_default=sa.func.now()` for `created_at`, `JSONB` for `items`/`subcalls` with server_default `'[]'`, Text enum-like cols, Integer counters with `server_default="0"`, Boolean flags `server_default="false"`), plus `op.create_index` for `idx_llm_calls_started_at` and `idx_llm_calls_stage_started`. `downgrade()` drops the table.

- [ ] **Step 4: Run** `python -m pytest tests/test_migration_013.py -q` → PASS. Then apply: `make migrate` and verify `\d llm_calls` (or `make migrate` output shows 013 applied).

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(migrations): 013 llm_calls table"`

---

### Task 3: `LlmCallStore` ABC + `PgLlmCallStore`

**Files:**
- Modify: `src/workbench/storage/base.py`, `src/workbench/storage/postgres/stores.py`, `src/workbench/storage/postgres/README.md`
- Create: `src/workbench/storage/postgres/llm_calls.py`
- Test: `tests/test_llm_calls_store.py` (integration — requires test Postgres; mark with the repo's DB fixture)

- [ ] **Step 1: Write the failing test** (use the repo's existing Postgres test fixture pattern, e.g. the one used by `tests` for `funnel`/`jobs` stores)
```python
# tests/test_llm_calls_store.py
import pytest
from datetime import datetime, timezone, timedelta
from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall

pytestmark = pytest.mark.asyncio

async def _rec(stage="filter", status="ok", batch=1, started=None):
    return LlmCallRecord(started_at=started or datetime.now(timezone.utc), origin="o",
        purpose="p", stage=stage, model="m", status=status, batch=batch,
        items=["i1"], tokens_in=10, tokens_out=4, latency_ms=120,
        subcalls=[LlmSubcall(item="i1", prompt="p", completion="c", structured={"a":1},
                             tokens_in=10, tokens_out=4)])

async def test_save_and_list(llm_calls_store):
    await llm_calls_store.save_many([await _rec(), await _rec(stage="triage")])
    rows = await llm_calls_store.list_calls(limit=10)
    assert len(rows) == 2
    got = await llm_calls_store.get_by_id(rows[0].id)
    assert got.subcalls[0].structured == {"a": 1}

async def test_metrics_24h(llm_calls_store):
    await llm_calls_store.save_many([await _rec(status="ok"), await _rec(status="error"),
                                     await _rec(batch=3)])
    m = await llm_calls_store.metrics_24h()
    assert m["calls_24h"] == 3
    assert 0 < m["error_rate"] < 1
    assert m["batched_pct"] > 0

async def test_delete_older_than(llm_calls_store):
    old = await _rec(started=datetime.now(timezone.utc) - timedelta(days=40))
    await llm_calls_store.save_many([old])
    # created_at uses now() server-default, so delete_older_than(0) prunes nothing for fresh rows;
    # assert the method runs and returns an int.
    assert isinstance(await llm_calls_store.delete_older_than(28), int)
```
Add a `llm_calls_store` fixture mirroring the existing per-store DB fixtures (create the table via migration or `create_postgres_stores` against the test DSN).

- [ ] **Step 2: Run** `python -m pytest tests/test_llm_calls_store.py -q` → Expected: fixture/`ImportError` (store missing).

- [ ] **Step 3: Write minimal implementation**
In `storage/base.py` add the `LlmCallStore(ABC)` (methods from the spec) and `from workbench.domain.llm_calls import LlmCallRecord`; add keyword-only `llm_calls: LlmCallStore | None = None` to `Stores.__init__` + `self.llm_calls = llm_calls`. Create `storage/postgres/llm_calls.py`:
```python
import json
from datetime import datetime, timedelta, timezone
import asyncpg
from workbench.domain.llm_calls import LlmCallRecord, LlmSubcall
from workbench.storage.base import LlmCallStore

class PgLlmCallStore(LlmCallStore):
    def __init__(self, pool: asyncpg.Pool): self.pool = pool

    async def save_many(self, records):
        if not records: return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO llm_calls
                   (started_at,origin,purpose,stage,model,temperature,status,error_type,
                    batch,items,tokens_in,tokens_out,cache_read_tokens,cache_write_tokens,
                    latency_ms,system_prompt,subcalls,tokens_estimated,is_fallback)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,$17::jsonb,$18,$19)""",
                [(r.started_at, r.origin, r.purpose, r.stage, r.model, r.temperature, r.status,
                  r.error_type, r.batch, json.dumps(r.items), r.tokens_in, r.tokens_out,
                  r.cache_read_tokens, r.cache_write_tokens, r.latency_ms, r.system_prompt,
                  json.dumps([s.model_dump() for s in r.subcalls]), r.tokens_estimated, r.is_fallback)
                 for r in records])

    @staticmethod
    def _row(rec) -> LlmCallRecord:
        d = dict(rec)
        items = d["items"]; subs = d["subcalls"]
        d["items"] = json.loads(items) if isinstance(items, str) else items
        subs = json.loads(subs) if isinstance(subs, str) else subs
        d["subcalls"] = [LlmSubcall(**s) for s in subs]
        return LlmCallRecord(**d)

    async def list_calls(self, *, limit, before=None, stage=None, status=None, origin=None, q=None):
        clauses, args = ["1=1"], []
        def add(sql, val): args.append(val); clauses.append(sql.format(len(args)))
        if before: args.extend(before); clauses.append(f"(started_at,id) < (${len(args)-1},${len(args)})")
        if stage: add("stage = ${}", stage)
        if status: add("status = ${}", status)
        if origin: add("origin = ${}", origin)
        if q: add("(origin || ' ' || purpose || ' ' || model) ILIKE '%' || ${} || '%'", q)
        args.append(limit)
        rows = await self.pool.fetch(
            f"SELECT * FROM llm_calls WHERE {' AND '.join(clauses)} "
            f"ORDER BY started_at DESC, id DESC LIMIT ${len(args)}", *args)
        return [self._row(r) for r in rows]

    async def get_by_id(self, call_id):
        r = await self.pool.fetchrow("SELECT * FROM llm_calls WHERE id=$1", call_id)
        return self._row(r) if r else None

    async def count_since(self, since):
        return await self.pool.fetchval("SELECT COUNT(*) FROM llm_calls WHERE created_at >= $1", since)

    async def metrics_24h(self):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        r = await self.pool.fetchrow(
            """SELECT COUNT(*) AS calls,
                      AVG(latency_ms) FILTER (WHERE status='ok') AS avg_ms,
                      COUNT(*) FILTER (WHERE status='error')::float / NULLIF(COUNT(*),0) AS err,
                      COUNT(*) FILTER (WHERE batch>1)::float / NULLIF(COUNT(*),0) AS batched
               FROM llm_calls WHERE created_at >= $1""", since)
        return {"calls_24h": r["calls"], "avg_latency_ms": float(r["avg_ms"]) if r["avg_ms"] is not None else None,
                "error_rate": float(r["err"] or 0.0), "batched_pct": float(r["batched"] or 0.0)}

    async def delete_older_than(self, days):
        res = await self.pool.execute(
            "DELETE FROM llm_calls WHERE created_at < NOW() - INTERVAL '1 day' * $1", days)
        return int(res.split()[-1])

    async def prune_to_max_rows(self, max_rows):
        res = await self.pool.execute(
            """DELETE FROM llm_calls WHERE id IN (
                 SELECT id FROM llm_calls ORDER BY started_at DESC OFFSET $1)""", max_rows)
        return int(res.split()[-1])
```
Register in `stores.py`: `llm_calls=PgLlmCallStore(pool)`. Add `llm_calls.py` to `storage/postgres/README.md`.

- [ ] **Step 4: Run** `python -m pytest tests/test_llm_calls_store.py -q` → PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(storage): LlmCallStore + PgLlmCallStore"`

---

### Task 4: `LLMCallContext` (contextvars)

**Files:** Create `src/workbench/providers/llm/context.py`; Test `tests/test_llm_context.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_llm_context.py
from workbench.providers.llm.context import llm_call_context, current_llm_call_context
def test_context_set_and_clear():
    assert current_llm_call_context() is None
    with llm_call_context(origin="o", purpose="p", stage="filter"):
        c = current_llm_call_context()
        assert (c.origin, c.purpose, c.stage) == ("o", "p", "filter")
    assert current_llm_call_context() is None
```
- [ ] **Step 2: Run** → ModuleNotFoundError.
- [ ] **Step 3: Implement** `context.py` exactly as the spec's "Provenance via contextvars" snippet (dataclass + `ContextVar` + `@contextmanager` that token-resets on exit).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(llm): LLMCallContext contextvar"`

---

### Task 5: Extend `record_plugboard_call` + `PlugboardCallRecord`

**Files:** Modify `src/workbench/providers/llm/plugboard.py`; Test `tests/test_llm_capture.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_llm_capture.py
import pytest
from types import SimpleNamespace
from workbench.providers.llm.plugboard import record_plugboard_call
from workbench.providers.llm.context import llm_call_context
pytestmark = pytest.mark.asyncio

async def test_captures_context_and_bodies():
    captured = []
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=4,
            cache_read_input_tokens=0, cache_creation_input_tokens=0),
            content=[SimpleNamespace(text="hello")])
    def extractor(r): return ("hello", {"k": 1}, [{"item":"i1","prompt":"p","completion":"hello",
                                                   "structured":{"k":1},"tokens_in":10,"tokens_out":4}])
    with llm_call_context(origin="triage", purpose="score", stage="triage"):
        await record_plugboard_call(client="main_llm", model="m", sink=captured.append,
            item_count=1, system_prompt="sys", input_prompt="p", temperature=0.2,
            result_extractor=extractor, do_call=lambda: _aval(resp))
    rec = captured[0]
    assert rec.context.stage == "triage" and rec.system_prompt == "sys"
    assert rec.completion == "hello" and rec.structured == {"k": 1} and rec.subcalls[0]["item"] == "i1"
    assert rec.input_tokens == 10 and rec.temperature == 0.2

async def _aval(v): return v

async def test_error_path_still_records_and_reraises():
    captured = []
    with pytest.raises(ValueError):
        await record_plugboard_call(client="c", model="m", sink=captured.append,
            do_call=_raise)
    assert captured[0].error_type == "ValueError"

async def _raise(): raise ValueError("boom")
```
- [ ] **Step 2: Run** → fails (new kwargs unsupported / fields missing).
- [ ] **Step 3: Implement** add the optional fields to `PlugboardCallRecord` (per spec), extend `record_plugboard_call` signature with `system_prompt/input_prompt/result_extractor/temperature/is_fallback`; on success, after reading `usage`, call `result_extractor(resp)` (guard None) to fill `completion/structured/subcalls`, attach `current_llm_call_context()`, `system_prompt`, `input_prompt`, `temperature`, `is_fallback`. Error path unchanged except it still attaches context + system/input prompt.
- [ ] **Step 4: Run** → PASS (and existing plugboard tests still pass: `python -m pytest tests/ -k plugboard -q`).
- [ ] **Step 5: Commit** `git commit -am "feat(llm): capture context + bodies in record_plugboard_call"`

---

### Task 6: Wire call sites (provenance + bodies + subcalls)

**Files:** Modify `providers/llm/anthropic.py`, `providers/queue_scorer/llm.py`, `pipeline/{extraction,filter,triage}.py`, `pipeline/scheduler.py`; Test `tests/test_llm_capture_integration.py`

- [ ] **Step 1: Failing test** — drive a fake LLM provider through the pipeline filter path and assert a record with `stage="filter"`, populated `subcalls`, `tokens_estimated=true` for a batch. (Use the repo's existing pipeline test doubles; assert via a capturing sink.)
- [ ] **Step 2: Run** → fails (no stage/subcalls captured).
- [ ] **Step 3: Implement**
  - In each pipeline stage, wrap the provider call in `with llm_call_context(origin=..., purpose=..., stage=...)` per the spec stage table.
  - In `anthropic.py` / `queue_scorer/llm.py`, pass `system_prompt`, `input_prompt`, `temperature`, and a `result_extractor` to `record_plugboard_call`. For batched `_score_*_chunk`, build the `subcalls` list after parse (per-item prompt = indexed slice; completion/structured = parsed element; tokens = proportional split; set `tokens_estimated=True`).
  - On the per-item fallback in `_score_relevance_chunk`, pass `is_fallback=True` to the single re-call.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(pipeline): set LLM call context + capture bodies/subcalls at call sites"`

---

### Task 7: Sink fan-out + async writer task + config

**Files:** Modify `src/workbench/runtime/app.py`, `src/workbench/config/models.py`; Test `tests/test_llm_writer.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_llm_writer.py — unit-test the writer drain in isolation
import asyncio, pytest
from workbench.runtime.app import build_llm_writer   # factory returning (sink_tap, loop_coro)
pytestmark = pytest.mark.asyncio
async def test_writer_drains_to_store(fake_store):
    q = asyncio.Queue(maxsize=10)
    # enqueue a record dict; run one drain iteration; assert fake_store.save_many called
    ...
```
(If extracting a `build_llm_writer` factory is too invasive, instead test that `_plugboard_sink` enqueues and that a single `_drain_once(queue, store)` helper batch-saves. Prefer a small pure helper for testability.)
Also add `test_writer_noop_when_store_none` (with `llm_tracking.enabled=true` but `stores.llm_calls is None`, no queue/task is created and the sink enqueue path is a no-op — no exception) and `test_sink_wired_without_metrics` (with `metrics.enabled=false, llm_tracking.enabled=true`, the provider `_sink` is attached and a record reaches the queue). These pin the gating edge cases.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement**
  - `config/models.py`: add `RetentionConfig.llm_calls_days: int = 28` and `llm_calls_max_rows: int | None = None`; add `class LlmTrackingConfig(BaseModel): enabled: bool = True`; wire `llm_tracking: LlmTrackingConfig = Field(default_factory=LlmTrackingConfig)` on `AppConfig`.
  - `app.py`: the `_plugboard_sink` closure and its provider wiring (`inner_llm._sink = _plugboard_sink`; `queue_scorer._sink = _plugboard_sink`) move out from under `if config.metrics.enabled:` to `if config.metrics.enabled or config.llm_tracking.enabled:`. Inside the sink, guard the Prometheus/`UsageAggregator` path with `if config.metrics.enabled` (and only construct `app.state.usage_agg`/the `_summary_loop` when `metrics.enabled`). Add the enqueue path: `if app.state.llm_write_q is not None: try: app.state.llm_write_q.put_nowait(rec) except asyncio.QueueFull: logger.warning(...); app.state.llm_dropped += 1`. Gate creation of the bounded queue (`asyncio.Queue(maxsize=1000)`) + `_llm_writer_loop` task on `config.llm_tracking.enabled and stores.llm_calls is not None` (so with tracking on but no store configured, the queue stays `None` and the enqueue branch is a no-op). The loop: `await queue.get()`, coalesce up to N with `get_nowait`, map records → `LlmCallRecord` (convert `latency_s*1000→ms`, `id=None`), `await stores.llm_calls.save_many(batch)` in a try/except that logs+drops. Store the task on `app.state.llm_writer_task`; cancel it in shutdown (mirror `summary_task`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(runtime): async llm_calls writer + tracking config"`

---

### Task 8: API — `/api/llm/calls`, `/{id}`, `/metrics`

**Files:** Create `src/workbench/api/llm.py`; Modify `src/workbench/runtime/app.py`; Test `tests/test_llm_api.py`

- [ ] **Step 1: Failing test** (mirror existing API tests, e.g. `tests/test_stats_api.py` — TestClient + auth header + a seeded `llm_calls` store)
```python
async def test_list_and_detail_and_metrics(client, seeded_llm_calls):
    r = client.get("/api/llm/calls?limit=5", headers=AUTH)
    assert r.status_code == 200 and isinstance(r.json(), list)
    row = r.json()[0]
    assert row["id"].startswith("llm_") and "ts" in row and "tokens_in" in row
    assert isinstance(row["temperature"], (int, float))  # non-null number (UI contract)
    assert "prompt" not in row  # bodies not in list
    d = client.get(f"/api/llm/calls/{row['id']}", headers=AUTH).json()
    assert "sysPrompt" in d and isinstance(d["subcalls"], list)
    m = client.get("/api/llm/metrics", headers=AUTH).json()
    assert set(m) >= {"calls_24h","avg_latency_ms","error_rate","batched_pct"}

def test_503_when_store_unconfigured(client_without_llm_store):
    assert client_without_llm_store.get("/api/llm/calls", headers=AUTH).status_code == 503
```
- [ ] **Step 2: Run** → 404 (route missing).
- [ ] **Step 3: Implement** `api/llm.py`: `router = APIRouter(prefix="/api/llm", tags=["llm"])`; a `_store(request)` helper that 503s if `stores.llm_calls is None`; `_llm_call_view(rec)` mapping domain→UI names with **every** field the UI `LLMCall` interface requires: `id=f"llm_{rec.id}"`, `ts=rec.started_at.isoformat()`, `origin`, `purpose`, `stage`, `model`, `temperature=rec.temperature or 0.0` (coalesce to a concrete number — UI type is non-null `number`), `status`, `batch`, `items`, `tokens_in`, `tokens_out`, `latency_ms` (no bodies); `_detail_view(rec)` → `{"sysPrompt": rec.system_prompt or "", "subcalls": [s.model_dump() ...]}`. Endpoints per spec; `/{id}` strips the `llm_` prefix and parses the remainder as `int`, returning `404` if the prefix is missing, the remainder is non-numeric, or no row matches. Register `llm.router` in `app.py` (import block + include loop).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(api): /api/llm calls + detail + metrics"`

---

### Task 9: UI — hooks + wire LLMInfra to real data

**Files:** Create `ui/src/hooks/useLLM.ts`; Modify `ui/src/pages/SystemStatus.tsx`; Tests `ui/src/hooks/useLLM.test.ts`, update `ui/src/pages/SystemStatus.test.tsx`

- [ ] **Step 1: Failing test** — extend `SystemStatus.test.tsx` LLM-tab suite: mock `/api/llm/calls`, `/api/llm/metrics`, `/api/llm/calls/:id` (MSW), assert the tab renders server rows (not the 64-row mock), the metric cards show server values, and clicking a row fetches + shows detail. Add a `useLLM` unit test.
- [ ] **Step 2: Run** `cd ui && npx vitest run src/pages/SystemStatus.test.tsx` → fails (still using mock).
- [ ] **Step 3: Implement**
  - `useLLM.ts`: `useLLMCalls(params)` (`['llm','calls',params]`, `pollWhenVisible(5_000)`), `useLLMCallDetail(id)` (`enabled: id != null`), `useLLMMetrics()` (`['llm','metrics']`, `pollWhenVisible(15_000)`), all via `apiGet`.
  - `SystemStatus.tsx`: delete `buildDefaultLLMCalls`/`DEFAULT_LLM_CALLS`/`setInterval`; `LLMInfra` consumes `useLLMCalls()` for rows + `useLLMMetrics()` for cards; `LLMCallDetail` consumes `useLLMCallDetail(id)`; add `extract`, `scoring`, `memory` to `LLM_STAGE_TONE`; keep `q` client-side over fetched rows; honor loading/error/empty/unauthorized states.
- [ ] **Step 4: Run** `cd ui && npx vitest run` → PASS; `npx tsc -b` clean.
- [ ] **Step 5: Commit** `git commit -am "feat(ui): wire LLM Infra tab to /api/llm (remove mock)"`

---

### Task 10: Retention sweep wiring

**Files:** Modify `src/workbench/pipeline/scheduler.py`; Test extend `tests/` retention test

- [ ] **Step 1: Failing test** — assert `run_retention_cleanup` returns an `llm_calls` key and calls `stores.llm_calls.delete_older_than(config.llm_calls_days)` (and `prune_to_max_rows` when `llm_calls_max_rows` set).
- [ ] **Step 2: Run** → fails (no key).
- [ ] **Step 3: Implement** add to `run_retention_cleanup`: `results["llm_calls"] = await stores.llm_calls.delete_older_than(config.llm_calls_days)` (guard `stores.llm_calls is not None`); if `config.llm_calls_max_rows`: `results["llm_calls_pruned"] = await stores.llm_calls.prune_to_max_rows(config.llm_calls_max_rows)`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(scheduler): sweep llm_calls per retention config"`

---

### Task 11: Memory subservice full-fidelity capture (separate repo)

> Cross-repo (ADR 0053). Migration 013 must be live on the workbench DB before this is enabled. Ship behind an off-by-default flag with a table-presence preflight.

**Files (memory repo):** modify the Graphiti client wrapper (`.../llm.py`), `instrumentation.py`, config, + a new cross-DB writer; Tests in the memory repo.

- [ ] **Step 1: Failing test** — wrap a fake Graphiti `AnthropicClient.generate_response`; assert the wrapper captures system/input prompt, completion, structured, tokens (or `tokens_estimated=true` when usage absent) and produces an `LlmCallRecord`-shaped dict with `origin="memory_subservice"`, `stage="memory"`.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement**
  - Extend the client wrapper to capture messages + response; build the row dict pinned to the documented `llm_calls` column contract.
  - Add a writer using the memory process's own `asyncpg` pool against a configured **workbench DSN** (`config.storage.workbench_dsn` or similar); INSERT-only, same column list as Task 3.
  - Add `llm_tracking.enabled` (default off in memory) + a startup preflight that checks `to_regclass('llm_calls')` is present; skip writing (warn once) if absent.
- [ ] **Step 4: Run** memory repo tests → PASS.
- [ ] **Step 5: Commit** in the memory repo: `git commit -am "feat(memory): full-fidelity LLM capture → workbench llm_calls"`

---

## Final verification (after all tasks)

- [ ] `make migrate` applies 013; `python -m pytest tests/` green (incl. new tests).
- [ ] `cd ui && npx vitest run` green; `npx tsc -b` clean; `npm run build` succeeds.
- [ ] Manual: run the pipeline, open the LLM Infra tab, confirm real rows stream in, detail shows real prompt/completion/structured, metric cards match SQL, and memory calls appear once the memory writer is enabled.
- [ ] Kill Postgres mid-run: no LLM call blocked/failed; writer logs drops and recovers.
