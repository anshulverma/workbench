# Raw LLM Input/Output in the Call Popup — Design

## Goal

In the LLM Infra view (System Status → LLM Infra), opening an LLM call shows the
**actual raw input that went into the model** (the full request: model,
params, system, the entire messages array, and any tools) and the **raw response
that came back** (the full SDK response object: all content blocks including
`tool_use`, `stop_reason`, `usage`). These appear **in addition to** the existing
structured input/output, and start **collapsed** in the popup.

Two adjacent fixes ship with this:

1. **De-duplicate "Completion" vs "Structured output".** For structured/tool-use
   calls these render the same content twice. Show exactly one per subcall.
2. **Fix the single-call body gap.** Non-batched calls currently persist with
   empty `subcalls`, so their Input/Completion body is dropped entirely in the
   popup. This is the likely root cause of "I still don't see the actual input
   and output of llm calls".

## Background

Today the capture path is:

```
messages.create  ──►  record_plugboard_call (plugboard.py)  ──►  _plugboard_sink
   (raw req+resp           (raw resp `resp` in scope but                │
    in scope)               discarded; only derived text kept)          ▼
                                                              _to_llm_record (app.py)
                                                                        │ queue
                                                                        ▼
                                                       save_many ──► llm_calls table
                                                                        │
                            popup ◄── GET /api/llm/calls/{id} ◄── get_by_id
```

What exists vs. what's missing:

- `PlugboardCallRecord` already carries `input_prompt` (a *flattened string*),
  `system_prompt`, `completion`, `structured`, and `subcalls`. It does **not**
  carry the structured request payload (messages array + tools) or the raw SDK
  response object.
- `record_plugboard_call` has the raw `resp` in scope (returned by `do_call`) but
  discards it after `result_extractor` derives `(completion, structured,
  subcalls)`.
- The raw request is built *inside* each provider's `do_call` closure
  (`messages=[...]`, `tools=[...]`), so plugboard cannot see it generically — the
  provider must hand it over.
- `_to_llm_record` (app.py) builds `subcalls` **only** from `rec.subcalls`. For
  single calls that path is empty (`record_plugboard_call` sets
  `rec.input_prompt`/`completion`/`structured` instead), so the popup body — which
  reads `subcalls[0]` — is dropped.
- The popup renders, per subcall: **Input** (`sub.prompt`), **Completion**
  (`sub.completion`), **Structured output** (`sub.structured` via `JsonHighlight`).
  For tool-use/structured calls, `completion` and `structured` show the same data.

## Decisions (locked during brainstorming)

- **Raw content = full request + full response JSON.** Raw input is the exact
  dict passed to `messages.create` (model, max_tokens, temperature, system, full
  messages array, tools, tool_choice). Raw output is the full SDK response object
  serialized via `resp.model_dump(mode="json")` (content blocks, stop_reason,
  usage). Both pretty-printed.
- **Granularity = call-level.** One `raw_request` + one `raw_response` per
  `messages.create` (i.e. per `LlmCallRecord`), not per subcall. A batch is one
  request producing many subcalls; raw I/O is shown once for the call.
- **Dedup = show one per subcall by type.** If `sub.structured` exists, render
  only **Structured output**; otherwise render only **Completion** (covers
  free-text and error cases). Never both.
- **Fix the single-call gap now.** Synthesize one subcall from the single-call
  fields when `rec.subcalls` is empty, so non-batched calls render a body.
- **Store verbatim, no redaction.** Raw payloads are persisted exactly as
  sent/received. This is an internal debugging tool and the DB already stores
  `system_prompt` and subcall prompts/completions verbatim; raw I/O is
  consistent with that. Existing retention (delete-older-than / prune-to-max)
  bounds growth.
- **Storage = nullable JSONB columns**, matching the existing `items` / `subcalls`
  JSONB pattern (not TEXT).
- **No request/response drift.** Each provider builds **one** `request` dict and
  uses it for *both* `messages.create(**request)` and `raw_request=request`, so
  the stored request cannot diverge from what was actually sent.

## Architecture & data flow

```
provider builds `request` dict
   │  messages.create(**request)        raw_request=request
   ▼                                          │
record_plugboard_call ── _serialize_response(resp) ──► raw_response
   │  PlugboardCallRecord{raw_request, raw_response, …}
   ▼
_to_llm_record  ── maps raw_* through; synthesizes single subcall if needed
   ▼
save_many  ── INSERT … raw_request::jsonb, raw_response::jsonb
   ▼
llm_calls (migration 016 adds raw_request, raw_response JSONB NULL)
   ▼
GET /api/llm/calls/{id} → _detail_view adds rawRequest / rawResponse
   ▼
LLMCallDetail popup: two collapsed call-level sections (JsonHighlight)
                     + per-subcall body shows ONE of Completion/Structured
```

## Components & changes

### 1. Capture — `providers/llm/plugboard.py`

- Add `raw_request: dict | None = None` and `raw_response: dict | None = None` to
  `PlugboardCallRecord`.
- Add `raw_request: dict | None = None` parameter to `record_plugboard_call`;
  attach it to the record on **both** the success and error paths (so a failed
  call still shows what was sent).
- Add a guarded module helper `_serialize_response(resp) -> dict | None`:
  returns `resp.model_dump(mode="json")` when available, else `None`; never
  raises (same defense-in-depth as `result_extractor`). Call it on the success
  path to populate `raw_response`. `raw_response` stays `None` on the error path.

### 2. Providers — `providers/llm/anthropic.py`, `providers/queue_scorer/llm.py`

For each `messages.create` call site (`_call_with_retry`,
`interpret_triage_response`, the batch scorer, queue_scorer):

- Build a local `request = {"model": …, "max_tokens": …, "messages": …, …}`
  (include `tools` / `tool_choice` / `temperature` / `system` where present).
- Call `do_call=lambda: self.client.messages.create(**request)`.
- Pass `raw_request=request` to `record_plugboard_call`.

`input_prompt`/`system_prompt` continue to be passed as before (structured view
is unchanged).

### 3. Domain — `domain/llm_calls.py`

- Add to `LlmCallRecord`: `raw_request: dict | None = None`,
  `raw_response: dict | None = None`. (Not on `LlmSubcall` — these are
  call-level.)

### 4. Migration — `migrations/versions/016_llm_raw_io.py`

- `ALTER TABLE llm_calls ADD COLUMN raw_request JSONB`, `ADD COLUMN raw_response
  JSONB` (both nullable, no default). Downgrade drops them. Revision chained
  after `015_entity_item_links`.

### 5. Store — `storage/postgres/llm_calls.py`

- Extend the `save_many` INSERT column list + values with
  `raw_request` (`$21::jsonb`), `raw_response` (`$22::jsonb`), passing
  `json.dumps(r.raw_request) if r.raw_request is not None else None` (same for
  response).
- In `_row`, deserialize `raw_request`/`raw_response` (json.loads when the value
  is a str; mirrors `items`/`subcalls`) before constructing `LlmCallRecord`.

### 6. Sink mapping + single-call fix — `runtime/app.py` `_to_llm_record`

- Map `raw_request=rec.raw_request`, `raw_response=rec.raw_response` onto the
  `LlmCallRecord`.
- **Single-call gap:** when `rec.subcalls` is falsy but the single-call fields
  are present, synthesize one `LlmSubcall(item=<first item path or "—">,
  prompt=rec.input_prompt or "", completion=rec.completion or "",
  structured=rec.structured, tokens_in=rec.input_tokens, tokens_out=rec.output_tokens)`.
  Batched behavior is unchanged.

### 7. Memory subservice — `src/memory/memory/llm_capture.py`

- **No change.** Its INSERT omits the new nullable columns, which default to
  NULL — safe. Memory-subservice calls will not carry raw I/O. Deliberate
  follow-up, not a silent gap.

### 8. API — `api/llm.py` `_detail_view`

- Add `"rawRequest": rec.raw_request` and `"rawResponse": rec.raw_response`
  (camelCase, matching `sysPrompt`). `null` when absent.

### 9. Popup — `ui/src/pages/SystemStatus.tsx`

- Extend `LLMCallDetailData` with `rawRequest?: unknown` and
  `rawResponse?: unknown`.
- **Dedup:** in the per-subcall body, render `Structured output` **only when**
  `sub.structured` is set; otherwise render `Completion`. Remove the always-both
  rendering.
- **Raw sections:** below the subcall body, add two **call-level** sections,
  **collapsed by default**, each a local `useState(false)` + Chevron toggle
  (mirroring `EnricherCard.tsx`), rendering the value through `<JsonHighlight
  json={JSON.stringify(value, null, 2)} />`. Labels: "Raw input (sent to LLM)"
  and "Raw output (from LLM)". A section renders nothing when its value is
  absent.

## Testing

- `tests/test_llm_calls_store.py` — round-trip `raw_request`/`raw_response`
  through `save_many` → `get_by_id`.
- `tests/test_plugboard_shim.py` — `_serialize_response` populates
  `raw_response` from a fake SDK response; `raw_request` flows through; a
  non-serializable response yields `raw_response=None` without raising.
- `tests/test_llm_api.py` — detail view exposes `rawRequest`/`rawResponse`; a
  single (non-batched) call now returns a non-empty `subcalls` body.
- `ui/src/pages/SystemStatus.test.tsx` — raw sections are collapsed by default
  and expand on click; the dedup shows exactly one of Completion / Structured
  output per subcall.

## Out of scope

- Raw I/O for memory-subservice calls (separate capture path; follow-up).
- Redaction/sanitization of stored raw payloads (explicitly verbatim).
- Per-subcall raw request/response (raw is call-level by construction).
- Truncation/size caps on raw payloads (retention bounds growth).
