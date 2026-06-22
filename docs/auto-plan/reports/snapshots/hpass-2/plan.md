# Raw LLM Input/Output in the Call Popup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the raw request payload (full prompt with context) and raw SDK response in the LLM Infra call popup, collapsed by default, in addition to the existing structured input/output — while de-duplicating Completion vs Structured output and fixing the dropped body on single (non-batched) calls.

**Architecture:** Capture the structured request dict (passed by each provider) and the serialized SDK response in `record_plugboard_call`, persist both as nullable JSONB columns on `llm_calls`, expose them via the detail API, and render two collapsed call-level sections in the popup. The single-call body gap is fixed in `_to_llm_record` by synthesizing one subcall from the single-call fields.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Alembic, Pydantic v2, pytest (live local Postgres at `postgres://workbench:workbench@localhost:5432/workbench`), React + TypeScript, Vitest, Testing Library.

**Conventions used below:**
- `PY` = `/home/anshulverma/workspace/workbench/.venv/bin/python` (repo-local venv; verified present).
- Backend tests: `PY -m pytest …` from repo root. Many tests need the local Postgres up and migrated.
- UI tests: `cd ui && npm run test -- <file>` (vitest).
- Source control: Sapling. Commit with `sl commit <paths> --message "…" --reason "<intent> - sl help commit"`. There is an unrelated pre-existing modification to `ui/src/components/AppShell.tsx` in the working copy — **never** stage or commit it; always pass explicit paths to `sl commit`.

---

### Task 1: Migration — add `raw_request` / `raw_response` columns

**Files:**
- Create: `src/workbench/migrations/versions/016_llm_raw_io.py`

- [ ] **Step 1: Write the migration**

```python
"""Raw LLM I/O: persist the full request payload and raw SDK response.

Adds two nullable JSONB columns to llm_calls so the LLM Infra popup can show
the actual raw input that went into the model (model/params/system/messages/
tools) and the raw response object (content blocks, stop_reason, usage),
alongside the existing structured input/output. Nullable + no default so the
memory-subservice INSERT (which omits these columns) keeps working.

Revision ID: 016
Revises: 015
Create Date: 2026-06-22
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_calls ADD COLUMN raw_request JSONB NULL")
    op.execute("ALTER TABLE llm_calls ADD COLUMN raw_response JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS raw_response")
    op.execute("ALTER TABLE llm_calls DROP COLUMN IF EXISTS raw_request")
```

- [ ] **Step 2: Apply the migration to the local DB**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m alembic upgrade head`
Expected: alembic logs `Running upgrade 015 -> 016`. (The pytest fixtures TRUNCATE but do not migrate, so the columns must exist in the live DB before store/API tests run.)

- [ ] **Step 3: Verify the columns exist**

Run:
```bash
cd /home/anshulverma/workspace/workbench && .venv/bin/python - <<'PY'
import asyncio, asyncpg
async def main():
    c = await asyncpg.connect("postgres://workbench:workbench@localhost:5432/workbench")
    rows = await c.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='llm_calls' AND column_name IN ('raw_request','raw_response') "
        "ORDER BY column_name"
    )
    print([(r["column_name"], r["data_type"]) for r in rows])
    await c.close()
asyncio.run(main())
PY
```
Expected: `[('raw_request', 'jsonb'), ('raw_response', 'jsonb')]`.

- [ ] **Step 4: Commit**

```bash
sl commit src/workbench/migrations/versions/016_llm_raw_io.py \
  --message "feat(db): add llm_calls.raw_request/raw_response JSONB columns" \
  --reason "add raw LLM I/O columns - sl help commit"
```

---

### Task 2: Domain model — add raw fields to `LlmCallRecord`

**Files:**
- Modify: `src/workbench/domain/llm_calls.py`
- Test: `tests/test_llm_calls_domain.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_calls_domain.py`:

```python
def test_llm_call_record_carries_raw_io():
    from datetime import datetime, timezone
    from workbench.domain.llm_calls import LlmCallRecord

    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o",
        purpose="p",
        stage="filter",
        model="m",
        status="ok",
        raw_request={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        raw_response={"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]},
    )
    assert rec.raw_request["messages"][0]["content"] == "hi"
    assert rec.raw_response["stop_reason"] == "end_turn"
    # Defaults are None when omitted.
    rec2 = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o", purpose="p", stage="filter", model="m", status="ok",
    )
    assert rec2.raw_request is None and rec2.raw_response is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_calls_domain.py -k raw_io -q`
Expected: FAIL — `TypeError`/`ValidationError` (`raw_request` is not a field).

- [ ] **Step 3: Add the fields**

In `src/workbench/domain/llm_calls.py`, inside `class LlmCallRecord`, add after `correlation_id: str | None = None` (line 63):

```python
    raw_request: dict | None = None
    raw_response: dict | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_calls_domain.py -k raw_io -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/domain/llm_calls.py tests/test_llm_calls_domain.py \
  --message "feat(llm): raw_request/raw_response on LlmCallRecord" \
  --reason "domain fields for raw LLM I/O - sl help commit"
```

---

### Task 3: Capture — `plugboard.py` records raw request + serialized response

**Files:**
- Modify: `src/workbench/providers/llm/plugboard.py`
- Test: `tests/test_plugboard_shim.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugboard_shim.py`:

```python
@pytest.mark.asyncio
async def test_shim_captures_raw_request_and_serialized_response():
    seen = []

    class FakeResp:
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        content = [SimpleNamespace(text="ok")]

        def model_dump(self, mode="python"):
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]}

    req = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    async def call():
        return FakeResp()

    await record_plugboard_call(
        client="main_llm", model="m", sink=seen.append, do_call=call, raw_request=req
    )
    rec = seen[0]
    assert rec.raw_request == req
    assert rec.raw_response == {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
    }


@pytest.mark.asyncio
async def test_shim_raw_response_none_when_unserializable():
    seen = []
    # No model_dump and not a pydantic model -> serializer returns None, no raise.
    resp = SimpleNamespace(usage=None, content=[])

    async def call():
        return resp

    await record_plugboard_call(
        client="main_llm", model="m", sink=seen.append, do_call=call
    )
    assert seen[0].raw_response is None


@pytest.mark.asyncio
async def test_shim_records_raw_request_on_error_path():
    seen = []
    req = {"model": "m", "messages": [{"role": "user", "content": "boom"}]}

    async def call():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await record_plugboard_call(
            client="main_llm", model="m", sink=seen.append, do_call=call, raw_request=req
        )
    assert seen[0].raw_request == req and seen[0].raw_response is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_plugboard_shim.py -k "raw" -q`
Expected: FAIL — `record_plugboard_call() got an unexpected keyword argument 'raw_request'`.

- [ ] **Step 3: Implement capture**

In `src/workbench/providers/llm/plugboard.py`:

3a. Add the two fields to `PlugboardCallRecord` (after `is_fallback: bool = False`, line 44):

```python
    raw_request: dict | None = None
    raw_response: dict | None = None
```

3b. Add a guarded serializer helper near the top of the module (after the `logger` line, ~line 22):

```python
def _serialize_response(resp: Any) -> dict | None:
    """Best-effort JSON-safe dump of an SDK response; never raises.

    Anthropic SDK responses are pydantic models, so ``model_dump(mode="json")``
    yields content blocks, stop_reason and usage. Anything without a usable
    ``model_dump`` (e.g. a test stub or a future SDK shape) yields ``None`` so a
    serialization quirk can never break a successful LLM call.
    """
    dump = getattr(resp, "model_dump", None)
    if not callable(dump):
        return None
    try:
        result = dump(mode="json")
    except Exception:
        try:
            result = dump()
        except Exception:
            return None
    return result if isinstance(result, dict) else None
```

3c. Add `raw_request: dict | None = None` to the `record_plugboard_call` signature (after `tokens_estimated: bool = False`, line 62):

```python
    raw_request: dict | None = None,
```

3d. On the **error path**, add `raw_request=raw_request` to the `PlugboardCallRecord(...)` constructed in the `except` block (alongside `input_prompt=input_prompt`, ~line 94):

```python
                        input_prompt=input_prompt,
                        raw_request=raw_request,
```

3e. On the **success path**, compute the serialized response before building the record and pass both fields. After `usage = getattr(resp, "usage", None)` (~line 104) add:

```python
        raw_response = _serialize_response(resp)
```

Then in the success-path `PlugboardCallRecord(...)` add (alongside `input_prompt=input_prompt`, ~line 131):

```python
                    input_prompt=input_prompt,
                    raw_request=raw_request,
                    raw_response=raw_response,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_plugboard_shim.py -q`
Expected: PASS (all, including the three new tests).

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/providers/llm/plugboard.py tests/test_plugboard_shim.py \
  --message "feat(llm): capture raw request + serialized response in plugboard" \
  --reason "plugboard raw I/O capture - sl help commit"
```

---

### Task 4: Store — persist + read back raw columns

**Files:**
- Modify: `src/workbench/storage/postgres/llm_calls.py`
- Test: `tests/test_llm_calls_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_calls_store.py`:

```python
async def test_save_and_get_round_trips_raw_io(llm_calls_store):
    rec = await _rec()
    rec.raw_request = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    rec.raw_response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]}
    await llm_calls_store.save_many([rec])
    rows = await llm_calls_store.list_calls(limit=1)
    got = await llm_calls_store.get_by_id(rows[0].id)
    assert got.raw_request["messages"][0]["content"] == "hi"
    assert got.raw_response["stop_reason"] == "end_turn"


async def test_save_and_get_raw_io_defaults_none(llm_calls_store):
    await llm_calls_store.save_many([await _rec()])
    rows = await llm_calls_store.list_calls(limit=1)
    got = await llm_calls_store.get_by_id(rows[0].id)
    assert got.raw_request is None and got.raw_response is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_calls_store.py -k raw_io -q`
Expected: FAIL — `raw_request` round-trips as `None` (column written but not in INSERT), `AssertionError` on `got.raw_request["messages"]` (TypeError: NoneType not subscriptable).

- [ ] **Step 3: Implement store changes**

In `src/workbench/storage/postgres/llm_calls.py`:

3a. Extend the INSERT column list + placeholders in `save_many` (lines 22-29). The column list becomes (add `raw_request,raw_response` after `correlation_id`) and the VALUES gains `$21::jsonb,$22::jsonb`:

```python
                    """INSERT INTO llm_calls
                       (started_at,origin,purpose,stage,model,temperature,status,error_type,
                        batch,items,tokens_in,tokens_out,cache_read_tokens,cache_write_tokens,
                        latency_ms,system_prompt,subcalls,tokens_estimated,is_fallback,
                        correlation_id,raw_request,raw_response)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,
                               $17::jsonb,$18,$19,$20,$21::jsonb,$22::jsonb)
                       RETURNING id""",
```

3b. Add the two bind values after `r.correlation_id,` (line 49):

```python
                    r.correlation_id,
                    json.dumps(r.raw_request) if r.raw_request is not None else None,
                    json.dumps(r.raw_response) if r.raw_response is not None else None,
```

3c. Deserialize in `_row` (after the `subcalls` handling, before the `return`, ~line 68):

```python
        for key in ("raw_request", "raw_response"):
            val = d.get(key)
            if isinstance(val, str):
                d[key] = json.loads(val)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_calls_store.py -q`
Expected: PASS (all, including the two new tests).

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/storage/postgres/llm_calls.py tests/test_llm_calls_store.py \
  --message "feat(llm): persist + read raw_request/raw_response in PgLlmCallStore" \
  --reason "store raw LLM I/O - sl help commit"
```

---

### Task 5: Sink mapping + single-call body fix — `app.py` `_to_llm_record`

**Files:**
- Modify: `src/workbench/runtime/app.py:41-93`
- Test: `tests/test_llm_writer.py`

> `_to_llm_record` maps a `PlugboardCallRecord` to an `LlmCallRecord`. Today it builds `subcalls` only from `rec.subcalls` (the batch path), so single calls — which set `rec.input_prompt`/`completion`/`structured` instead — persist an empty body. This task threads the raw fields through and synthesizes one subcall when the batch list is empty.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_llm_writer.py` (import `_to_llm_record` and `PlugboardCallRecord`). Do NOT redefine the module-level `_ctx()` already at the top of this file — it has no `item_paths` and is relied on by existing tests. `LLMCallContext` is already imported at the top of the file. Add a separate helper:

```python
def _ctx_with_item():
    return LLMCallContext(
        origin="filter", purpose="classify", stage="filter",
        item_paths=("D1",), correlation_id="corr-1",
    )


def test_to_llm_record_threads_raw_io():
    from workbench.runtime.app import _to_llm_record
    from workbench.providers.llm.plugboard import PlugboardCallRecord

    rec = _to_llm_record(
        PlugboardCallRecord(
            client="main_llm", model="m", context=_ctx_with_item(),
            raw_request={"model": "m", "messages": []},
            raw_response={"stop_reason": "end_turn"},
        )
    )
    assert rec.raw_request == {"model": "m", "messages": []}
    assert rec.raw_response == {"stop_reason": "end_turn"}


def test_to_llm_record_synthesizes_single_subcall():
    from workbench.runtime.app import _to_llm_record
    from workbench.providers.llm.plugboard import PlugboardCallRecord

    rec = _to_llm_record(
        PlugboardCallRecord(
            client="main_llm", model="m", context=_ctx_with_item(),
            input_prompt="the full prompt",
            completion="the answer",
            structured={"verdict": "ok"},
            input_tokens=12, output_tokens=3,
            subcalls=None,  # single (non-batch) call
        )
    )
    assert len(rec.subcalls) == 1
    s = rec.subcalls[0]
    assert s.prompt == "the full prompt"
    assert s.completion == "the answer"
    assert s.structured == {"verdict": "ok"}
    assert s.tokens_in == 12 and s.tokens_out == 3
    assert s.item == "D1"  # first context item path


def test_to_llm_record_batch_subcalls_unchanged():
    from workbench.runtime.app import _to_llm_record
    from workbench.providers.llm.plugboard import PlugboardCallRecord

    rec = _to_llm_record(
        PlugboardCallRecord(
            client="main_llm", model="m", context=_ctx_with_item(),
            subcalls=[{"item": "0", "prompt": "p", "completion": "c",
                       "structured": {"x": 1}, "tokens_in": 5, "tokens_out": 2}],
        )
    )
    assert len(rec.subcalls) == 1 and rec.subcalls[0].item == "0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_writer.py -k "raw_io or single_subcall or subcalls_unchanged" -q`
Expected: FAIL — `raw_request` is `None` on the result, and the single-call case yields `rec.subcalls == []` (IndexError / length 0).

- [ ] **Step 3: Implement the mapping**

In `src/workbench/runtime/app.py`, replace the `subcalls = [...]` comprehension (lines 57-67) with a version that falls back to a synthesized single subcall:

```python
    subcalls = [
        LlmSubcall(
            item=s["item"],
            prompt=s.get("prompt", ""),
            completion=s.get("completion", ""),
            structured=s.get("structured"),
            tokens_in=(s.get("tokens_in") or 0),
            tokens_out=s.get("tokens_out"),
        )
        for s in (rec.subcalls or [])
    ]
    # Single (non-batch) calls populate input_prompt/completion/structured on the
    # record rather than subcalls; synthesize one subcall so the popup renders a
    # body (without this, single calls show no Input/Completion at all).
    if not subcalls and (
        rec.input_prompt is not None
        or rec.completion is not None
        or rec.structured is not None
    ):
        item_label = (
            rec.context.item_paths[0]
            if rec.context and rec.context.item_paths
            else "—"
        )
        subcalls = [
            LlmSubcall(
                item=item_label,
                prompt=rec.input_prompt or "",
                completion=rec.completion or "",
                structured=rec.structured,
                tokens_in=rec.input_tokens or 0,
                tokens_out=(None if rec.error_type else rec.output_tokens),
            )
        ]
```

Then add the raw fields to the `LlmCallRecord(...)` return (after `correlation_id=...`, line 92):

```python
        correlation_id=(rec.context.correlation_id if rec.context else None),
        raw_request=rec.raw_request,
        raw_response=rec.raw_response,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_writer.py -q`
Expected: PASS (all). If `tests/test_llm_writer.py` lacks the `LLMCallContext` constructor signature shown, adjust `_ctx()` to match the real dataclass (run `.venv/bin/python -c "from workbench.providers.llm.context import LLMCallContext; import inspect; print(inspect.signature(LLMCallContext))"`).

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/runtime/app.py tests/test_llm_writer.py \
  --message "feat(llm): thread raw I/O + synthesize single-call subcall in sink" \
  --reason "sink mapping + single-call body fix - sl help commit"
```

---

### Task 6: Providers pass `raw_request` (no request/response drift)

**Files:**
- Modify: `src/workbench/providers/llm/anthropic.py` (`_call_with_retry` ~line 577; `interpret_triage_response` ~line 505)
- Modify: `src/workbench/providers/queue_scorer/llm.py` (`score_urgency` ~line 73; `_score_urgency_chunk` ~line 174)
- Test: `tests/test_anthropic_llm.py`

> Each call site builds **one** `request` dict and uses it for both `messages.create(**request)` and `raw_request=request`, so the stored request always equals what was sent. There are exactly four real `messages.create` sites in the providers: `_call_with_retry` (the chokepoint for single calls **and** batch relevance scoring), `interpret_triage_response` (tools), and both `queue_scorer` paths (`score_urgency` single-item, `_score_urgency_chunk` batch). All four are wired below.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_anthropic_llm.py` (mirror the existing fake-client + sink setup used elsewhere in that file; if a helper like `_make_llm()` exists, reuse it). The test asserts the captured record carries the actual messages payload:

```python
@pytest.mark.asyncio
async def test_call_with_retry_records_raw_request(monkeypatch):
    from types import SimpleNamespace
    from workbench.providers.llm.anthropic import AnthropicLLM

    seen = []

    class FakeMessages:
        async def create(self, **kwargs):
            # echo enough for content[0].text and usage
            return SimpleNamespace(
                content=[SimpleNamespace(text="hello", type="text")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                model_dump=lambda mode="json": {"content": [{"type": "text", "text": "hello"}]},
            )

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-x"
    llm.client = SimpleNamespace(messages=FakeMessages())
    llm._sink = seen.append

    out = await llm._call_with_retry("classify this item")
    assert out == "hello"
    rec = seen[-1]
    assert rec.raw_request["model"] == "claude-x"
    assert rec.raw_request["messages"] == [{"role": "user", "content": "classify this item"}]
    assert rec.raw_request["max_tokens"] == 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_anthropic_llm.py -k raw_request -q`
Expected: FAIL — `rec.raw_request` is `None`.

- [ ] **Step 3: Wire the three call sites**

3a. `anthropic.py` `_call_with_retry` — replace the `record_plugboard_call(...)` block (lines 566-582) so the request dict is built once:

```python
                request = {
                    "model": self.model,
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}],
                }
                response = await record_plugboard_call(
                    client="main_llm",
                    model=self.model,
                    sink=self._sink,
                    item_count=item_count,
                    input_prompt=prompt,
                    system_prompt=system_prompt,
                    result_extractor=result_extractor,
                    temperature=temperature,
                    is_fallback=is_fallback,
                    tokens_estimated=tokens_estimated,
                    raw_request=request,
                    do_call=lambda: self.client.messages.create(**request),
                )
```

> The `request = {...}` assignment stays INSIDE the `for attempt in range(max_retries)` loop (it replaces the existing in-loop `record_plugboard_call(...)` at lines 566-582). It is rebuilt identically each attempt; the `do_call` lambda binds the current `request`, so retries send and record the same payload.

3b. `anthropic.py` `interpret_triage_response` — replace the `record_plugboard_call(...)` block (lines 499-512):

```python
            request = {
                "model": self.model,
                "max_tokens": 1000,
                "tools": tools,
                "tool_choice": {"type": "tool", "name": "interpret_response"},
                "messages": messages,
            }
            response = await record_plugboard_call(
                client="main_llm",
                model=self.model,
                sink=self._sink,
                input_prompt=messages[0]["content"],
                result_extractor=_interpret_result,
                raw_request=request,
                do_call=lambda: self.client.messages.create(**request),
            )
```

3c. `queue_scorer/llm.py` — replace the `record_plugboard_call(...)` block (lines 174-187):

```python
            request = {
                "model": self.model,
                "max_tokens": min(4096, 40 * len(chunk) + 100),
                "messages": [{"role": "user", "content": prompt}],
            }
            response = await record_plugboard_call(
                client="queue_scorer",
                model=self.model,
                sink=self._sink,
                item_count=len(chunk),
                input_prompt=prompt,
                result_extractor=_batch_urgency_result,
                tokens_estimated=True,
                raw_request=request,
                do_call=lambda: self.client.messages.create(**request),
            )
```

3d. `queue_scorer/llm.py` `score_urgency` (single-item path) — replace the `record_plugboard_call(...)` block (lines 73-85):

```python
            request = {
                "model": self.model,
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            }
            response = await record_plugboard_call(
                client="queue_scorer",
                model=self.model,
                sink=self._sink,
                input_prompt=prompt,
                result_extractor=_urgency_result,
                is_fallback=is_fallback,
                raw_request=request,
                do_call=lambda: self.client.messages.create(**request),
            )
```

> This is the 4th and final real `messages.create` site in the providers (verified via `grep -rn "messages.create" src/workbench`). Covering it means every non-memory LLM call carries `raw_request`. The memory subservice (`src/memory/memory/llm_capture.py`) uses a separate capture path and stays out of scope.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_anthropic_llm.py -q`
Expected: PASS. If `AnthropicLLM.__new__` bypass fails because `_call_with_retry` references an attribute not set here, set it on the instance in the test (read the error, add the missing attribute) — do not change production code to accommodate the test.

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/providers/llm/anthropic.py src/workbench/providers/queue_scorer/llm.py tests/test_anthropic_llm.py \
  --message "feat(llm): providers pass raw_request to plugboard" \
  --reason "wire raw_request at call sites - sl help commit"
```

---

### Task 7: API — expose `rawRequest` / `rawResponse` in the detail view

**Files:**
- Modify: `src/workbench/api/llm.py:44-50`
- Test: `tests/test_llm_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_llm_api.py` (mirror the existing detail-view test setup — it saves an `LlmCallRecord` via the store fixture and GETs `/api/llm/calls/llm_{id}`; reuse that test's app/client construction):

```python
@pytest.mark.asyncio
async def test_detail_view_exposes_raw_io(client, app_with_state):
    stores = app_with_state.state.stores
    rec = LlmCallRecord(
        started_at=datetime.now(timezone.utc),
        origin="o", purpose="p", stage="filter", model="m", status="ok",
        subcalls=[LlmSubcall(item="i1", prompt="p", completion="c",
                             structured={"a": 1}, tokens_in=1, tokens_out=1)],
        raw_request={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        raw_response={"stop_reason": "end_turn"},
    )
    await stores.llm_calls.save_many([rec])
    row = (await stores.llm_calls.list_calls(limit=1))[0]

    r = await client.get(f"/api/llm/calls/llm_{row.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["rawRequest"]["messages"][0]["content"] == "hi"
    assert body["rawResponse"]["stop_reason"] == "end_turn"
```

> Verified: `test_llm_api.py` uses the `(client, app_with_state)` fixtures (an `httpx.AsyncClient` over `ASGITransport`), reads stores via `app_with_state.state.stores`, and fetches the saved id via `list_calls(limit=1)`. `LlmCallRecord`/`LlmSubcall`/`datetime` are already imported at the top of the file, and each test carries its own `@pytest.mark.asyncio` (no module-level `pytestmark`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_api.py -k raw_io -q`
Expected: FAIL — `KeyError: 'rawRequest'`.

- [ ] **Step 3: Implement**

In `src/workbench/api/llm.py`, extend `_detail_view` (lines 44-50):

```python
def _detail_view(rec, linked_items: list[dict]) -> dict:
    """Map LlmCallRecord to the detail-view JSON shape (prompt + subcalls)."""
    return {
        "sysPrompt": rec.system_prompt or "",
        "subcalls": [s.model_dump() for s in rec.subcalls],
        "linked_items": linked_items,
        "rawRequest": rec.raw_request,
        "rawResponse": rec.raw_response,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/test_llm_api.py -q`
Expected: PASS (all — existing detail/list tests still green).

- [ ] **Step 5: Commit**

```bash
sl commit src/workbench/api/llm.py tests/test_llm_api.py \
  --message "feat(llm): expose rawRequest/rawResponse in call detail API" \
  --reason "API raw I/O fields - sl help commit"
```

---

### Task 8: Popup — dedup Completion/Structured + collapsed raw sections

**Files:**
- Modify: `ui/src/pages/SystemStatus.tsx` (`LLMCallDetailData` type ~line 235; `LLMCallDetail` body ~lines 1097-1178)
- Test: `ui/src/pages/SystemStatus.test.tsx`

- [ ] **Step 1: Write the failing tests**

8a. Extend the existing `LLM_DETAIL` fixture (~line 83) to include raw fields:

```javascript
const LLM_DETAIL = {
  sysPrompt: 'You are a noise filter. Return whether the rule fires.',
  subcalls: [
    {
      item: 'D12871',
      prompt: '[item D12871] classify · drop-confidence',
      completion: '{"fires": false, "confidence": 88}',
      structured: { fires: false, confidence: 88 },
      tokens_in: 420,
      tokens_out: 88,
    },
  ],
  linked_items: [{ id: 7001, path: '7001', summary: 'solo item' }],
  rawRequest: { model: 'claude-x', messages: [{ role: 'user', content: 'classify D12871' }] },
  rawResponse: { stop_reason: 'tool_use', content: [{ type: 'tool_use', name: 'classify' }] },
}
```

8b. Add tests in the popup `describe` block (near the existing "opens a call detail dialog" test):

```javascript
  it('shows raw input/output sections collapsed by default and expands them', async () => {
    await openLLMTab()
    await userEvent.click(screen.getAllByTestId('llm-log-row')[0])
    const dialog = await screen.findByRole('dialog')
    // Section headers are present...
    expect(within(dialog).getByText(/raw input/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/raw output/i)).toBeInTheDocument()
    // ...but the raw JSON is hidden until expanded.
    expect(within(dialog).queryByTestId('llm-raw-request')).not.toBeInTheDocument()
    await userEvent.click(within(dialog).getByText(/raw input/i))
    expect(await within(dialog).findByTestId('llm-raw-request')).toHaveTextContent('claude-x')
    await userEvent.click(within(dialog).getByText(/raw output/i))
    expect(await within(dialog).findByTestId('llm-raw-response')).toHaveTextContent('tool_use')
  })

  it('shows structured output OR completion, never both', async () => {
    await openLLMTab()
    await userEvent.click(screen.getAllByTestId('llm-log-row')[0])
    const dialog = await screen.findByRole('dialog')
    // This subcall HAS structured output -> show Structured output, hide Completion.
    expect(within(dialog).getByText('Structured output')).toBeInTheDocument()
    expect(within(dialog).queryByText('Completion')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/anshulverma/workspace/workbench/ui && npm run test -- src/pages/SystemStatus.test.tsx`
Expected: FAIL — "raw input" text not found; "Completion" still present.

- [ ] **Step 3: Implement the type change**

In `ui/src/pages/SystemStatus.tsx`, extend `LLMCallDetailData` (~line 235) — add after `linked_items`:

```typescript
  rawRequest?: unknown
  rawResponse?: unknown
```

- [ ] **Step 4: Implement the dedup**

Replace the Completion + Structured blocks (lines 1135-1176) with a single either/or block:

```tsx
            {sub.structured ? (
              <div>
                <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                  Structured output
                </span>
                <div
                  style={{
                    borderRadius: 'var(--radius-card,6px)',
                    border: '1px solid var(--border)',
                    overflow: 'hidden',
                  }}
                  data-testid="llm-structured-output"
                >
                  <JsonHighlight json={JSON.stringify(sub.structured, null, 2)} />
                </div>
              </div>
            ) : (
              <div>
                <span className="label-mono" style={{ fontSize: 10, display: 'block', marginBottom: 6 }}>
                  Completion <span style={{ color: 'var(--muted-foreground)' }}>↑{sub.tokens_out ?? '—'} tok</span>
                </span>
                <pre
                  style={{
                    margin: 0,
                    padding: 12,
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    lineHeight: 1.5,
                    background: 'var(--surface-lowest)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-card,6px)',
                    color: call.status === 'error' ? 'var(--error-text)' : 'var(--foreground)',
                  }}
                >
                  {sub.completion}
                </pre>
              </div>
            )}
```

- [ ] **Step 5: Implement the collapsed raw sections**

5a. Add a small local collapsible component above `function LLMCallDetail` (top-level in the file). It mirrors the `useState(false)` + Chevron toggle pattern from `EnricherCard.tsx`:

```tsx
function RawSection({
  label,
  value,
  testId,
}: {
  label: string
  value: unknown
  testId: string
}) {
  const [open, setOpen] = useState(false)
  if (value == null) return null
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="label-mono"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 10,
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          color: 'var(--foreground)',
          marginBottom: open ? 6 : 0,
        }}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {label}
      </button>
      {open && (
        <div
          style={{
            borderRadius: 'var(--radius-card,6px)',
            border: '1px solid var(--border)',
            overflow: 'hidden',
          }}
          data-testid={testId}
        >
          <JsonHighlight json={JSON.stringify(value, null, 2)} />
        </div>
      )}
    </div>
  )
}
```

> Verified: `useState` is already imported in `SystemStatus.tsx` (line 7). `getIcon` is NOT available here (it is a private, non-exported function inside `EnricherCard.tsx`). Add `ChevronRight` and `ChevronDown` to the existing `lucide-react` import block (lines 9-30) and render them directly as shown; do not reference `getIcon`. `JsonHighlight` is already imported in this file.

5b. Render the two sections as the **last children of the scrollable body grid** (the `<div style={{ ... display: 'grid' ... }}>` that opens at ~line 1112 and closes at ~line 1177). Insert them immediately BEFORE that grid's closing `</div>`, i.e. directly after the dedup Completion/Structured block from Step 4:

```tsx
            <RawSection label="Raw input (sent to LLM)" value={detail.rawRequest} testId="llm-raw-request" />
            <RawSection label="Raw output (from LLM)" value={detail.rawResponse} testId="llm-raw-response" />
```

> These read `detail.rawRequest`/`detail.rawResponse` (call-level), not `sub.*`. Place them inside the `body: input / completion / structured` grid container so they stack below the subcall body with the same spacing.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/anshulverma/workspace/workbench/ui && npm run test -- src/pages/SystemStatus.test.tsx`
Expected: PASS (all, including the two new tests and the pre-existing "Structured output" / subcall-selector tests).

- [ ] **Step 7: Commit**

```bash
sl commit ui/src/pages/SystemStatus.tsx ui/src/pages/SystemStatus.test.tsx \
  --message "feat(ui): raw LLM I/O sections + dedup completion/structured in popup" \
  --reason "popup raw I/O + dedup - sl help commit"
```

---

### Task 9: Full verification

- [ ] **Step 1: Backend suite**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m pytest tests/ -q`
Expected: PASS (no regressions). Pay attention to `test_llm_capture*`, `test_llm_calls_retention.py`, `test_llm_calls_lineage.py`, `test_llm_linked_items_api.py` — they touch the `llm_calls` table and must stay green with the new nullable columns.

- [ ] **Step 2: Lint**

Run: `cd /home/anshulverma/workspace/workbench && .venv/bin/python -m ruff check src/ tests/`
Expected: clean (fix any new lint).

- [ ] **Step 3: UI suite**

Run: `cd /home/anshulverma/workspace/workbench/ui && npm run test`
Expected: PASS.

- [ ] **Step 4: Manual smoke (optional but recommended)**

Bring up the stack (`make up` or the project's run flow), open System Status → LLM Infra, click a recent call. Confirm: (a) single calls now show an Input + one of Completion/Structured; (b) "Raw input (sent to LLM)" and "Raw output (from LLM)" appear collapsed; (c) expanding shows the full messages payload and the raw response JSON.

---

## Notes / out of scope (carried from the spec)

- **Memory-subservice calls** (`src/memory/memory/llm_capture.py`) intentionally do not populate raw I/O — its INSERT omits the new nullable columns. Follow-up if raw is wanted there.
- **Plain-text single calls** that run through `_call_with_retry` with no `result_extractor` capture no structured `completion`; their text still appears in the **Raw output** section. Acceptable for v1.
- **No redaction** of stored raw payloads (verbatim, consistent with existing `system_prompt`/subcall storage); **no truncation** (retention bounds growth).
- Raw is **call-level** (one request/response per `messages.create`), not per-subcall.
