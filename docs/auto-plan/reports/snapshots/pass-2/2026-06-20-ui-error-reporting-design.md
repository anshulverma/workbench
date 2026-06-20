# UI Error Reporting — Design

## Goal

Let the workbench UI (React app, served over HTTPS on a loopback/SSH-tunnel
isolated devserver port) ship client-side errors back to the server so they land
in the same `data/logs` JSON stream that `make logs` and the in-app `LogStream`
already read. Today client errors are only visible in the browser console; the
`ErrorBoundary` reports nowhere and there are no global handlers.

## Decisions (locked during brainstorming)

- **Capture scope:** broad — `window.onerror` (uncaught JS), `unhandledrejection`
  (promise rejections), the React `ErrorBoundary`, failed API calls (`ApiError`
  in `api.ts`), and wrapped `console.error` / `console.warn`.
- **Endpoint auth:** auth-exempt (loopback-only), like `/api/auth/token`. Error
  reporting must work even when the token flow itself is broken.
- **Delivery:** batched + throttled — buffer, flush on interval/size, flush via
  `navigator.sendBeacon` on page hide/unload, with client-side dedup and a
  per-session rate cap.
- **Storage:** logs only (`data/logs` via structlog). No DB table / migration.

## Approaches considered

- **A — Dedicated reporter module + thin auth-exempt route (CHOSEN).** New
  `ui/src/lib/error-reporter.ts` owns capture/buffer/throttle/transport; new
  `src/workbench/api/client_logs.py` validates and logs. Clean seams, testable,
  redaction comes free from the existing `SanitizingProcessor`.
- **B — Third-party SDK (Sentry / self-hosted GlitchTip).** Mature but adds an
  external dependency + infra for a single-user loopback tool and routes data
  off-box. Rejected as overkill.
- **C — Inline handlers in `main.tsx` + fold into `debug.py`.** Fewer files, but
  bloats `main.tsx`, conflates `debug.py`'s read-only inspection role with a
  write-ingestion endpoint, and is hard to unit-test. Rejected.

## Architecture & data flow

```
window.onerror / unhandledrejection ┐
React ErrorBoundary.componentDidCatch ┤
api.ts ApiError (failed fetch)        ┼─► error-reporter.ts ─► buffer (dedup + rate-cap)
console.error / console.warn (wrapped)┘                            │
                                              flush: interval | size | pagehide(sendBeacon)
                                                                    ▼
                                   POST /api/client-logs  (auth-exempt, loopback)
                                                                    ▼
                            client_logs.py: validate → structlog.get_logger("workbench.client")
                                                                    ▼
                       SanitizingProcessor (redact emails/phones, truncate) → data/logs JSON
                                                                    ▼
                                     visible in `make logs` and the UI LogStream
```

## Component 1 — Server endpoint (`src/workbench/api/client_logs.py`)

New per-domain route module following the existing convention (cf. `debug.py`,
`feedback.py`).

- `router = APIRouter(prefix="/api/client-logs", tags=["client-logs"])`, added to
  the router list in `runtime/app.py` (the `for r in [ ... ]: app.include_router(r)`
  loop, ~lines 541-568, after the last entry `llm.router`; the import goes in the
  alphabetized `from workbench.api import ( ... )` block, ~lines 513-539).
- Pydantic models:
  - `ClientLogEvent`:
    - `level: Literal["error", "warn", "info"]`
    - `kind: Literal["uncaught", "unhandledrejection", "react", "api", "console"]`
    - `message: str` (`max_length`, e.g. 4000)
    - `stack: str | None` (`max_length`, e.g. 16000)
    - `component_stack: str | None`
    - `source: str | None` (file/script URL)
    - `line: int | None`, `col: int | None`
    - `url: str | None` (page URL / route hash)
    - `ts: int` (client epoch ms)
    - `request_id: str | None` (correlates to `X-Request-ID` from `ApiError`)
    - `count: int = 1` (dedup multiplier)
    - `extra: dict | None` (e.g. `{ "status": 500 }` for API errors)
  - `ClientLogBatch`: `{ events: list[ClientLogEvent] }`
- `POST /` (`@router.post("")`):
  - Reject batches with `len(events) > 50` → `413`.
  - For each event, emit one structlog record via a dedicated logger
    `structlog.get_logger("workbench.client")` at the mapped level
    (`error`→error, `warn`→warning, `info`→info), with a fixed event name
    `"client_error"` and the event fields as structured kwargs.
  - Return `204 No Content`.
- The endpoint accepts `Content-Type: application/json` (the client sets the
  `sendBeacon` Blob type to `application/json` so FastAPI parses it normally).

**Auth exemption:** add `or path == "/api/client-logs"` to the exempt clause in
`runtime/auth.py` (currently `if path.startswith("/ui") or path ==
"/api/auth/token":`, ~line 42).

**Redaction / truncation:** automatic — `SanitizingProcessor`
(`telemetry/privacy.py`, wired into the structlog chain via the
`extra_processors` arg of `setup_logging` in `telemetry/logging.py`) already
redacts emails/phones and truncates long strings on every event. One change:
add `"component_stack"` to `NO_TRUNCATE_KEYS` (which already contains `"stack"`)
so React component stacks are kept full (still PII-redacted) rather than cut at
`max_content_in_logs`.

**PII in `extra`:** `SanitizingProcessor` only redacts *string* values
(`if not isinstance(value, str): continue`), so it tolerates `None`/`int`/`dict`
kwargs without raising — but a `dict` `extra` (e.g. `{"status": 500}`) is passed
through unredacted. The endpoint therefore JSON-serializes `extra` to a string
(`extra_json`) before logging so any PII inside it is also redacted; the original
typed value is dropped.

## Component 2 — Client reporter (`ui/src/lib/error-reporter.ts`)

Self-contained module owning all capture and transport.

- `installErrorReporter(): void` — idempotent; called once from `main.tsx` before
  render. Installs:
  - `window.addEventListener('error', ...)` → `kind: "uncaught"`, level `error`.
  - `window.addEventListener('unhandledrejection', ...)` →
    `kind: "unhandledrejection"`, level `error`.
  - wraps `console.error` / `console.warn`, keeping the original references and
    always calling through to them (`kind: "console"`, level `error`/`warn`).
- `reportClientError(event: Partial<ClientLogEvent> & {...}): void` — public fn
  used by `ErrorBoundary` and `api.ts`.
- **Buffer + throttle:**
  - In-memory queue. Flush triggers: (a) interval ~5s, (b) buffer length ≥ 20,
    (c) `pagehide` and `visibilitychange → hidden`.
  - **Dedup:** signature = `kind | message | stack.slice(0,200)`. Identical
    events within the buffer window collapse into one with `count++`.
  - **Rate cap:** ≤ ~100 events/session. On hit, drop further events and enqueue
    a single `"client reporter rate-limited"` marker event.
- **Transport:**
  - interval/size flush → `fetch('/api/client-logs', { method:'POST',
    keepalive:true, headers:{'Content-Type':'application/json'}, body })` — no
    auth header (endpoint is exempt).
  - unload flush → `navigator.sendBeacon('/api/client-logs', new Blob([body],
    { type:'application/json' }))`.
- **Loop prevention (critical — we wrap `console.error`):**
  - module-level `inReporter` reentrancy guard; wrapped console fns skip capture
    while it is set.
  - the reporter NEVER calls `console.error`/`console.warn` on its own failures;
    transport errors are swallowed silently.
  - reporter-origin diagnostics are tagged so they cannot feed back into capture.

## Component 3 — Wiring (small touches)

- `ui/src/main.tsx`: call `installErrorReporter()` before
  `ReactDOM.createRoot(...).render(...)`.
- `ui/src/components/ErrorBoundary.tsx`: add
  `componentDidCatch(error, info)` → `reportClientError({ kind:'react',
  level:'error', message: error.message, stack: error.stack,
  component_stack: info.componentStack })`. Render fallback unchanged.
- `ui/src/lib/api.ts`: in `request()`'s error path, call `reportClientError({
  kind:'api', level:'warn', message: detail, request_id: requestId, url: path,
  extra:{ status: res.status } })` before throwing `ApiError`. Warn level + dedup
  keep expected 4xx noise down; the server already logs its own responses, so
  this exists for client-side correlation.

## Error handling & abuse prevention

- Client transport failures are swallowed (never surfaced as new console errors —
  would otherwise loop).
- Reentrancy guard prevents the console wrap from recursing.
- Client rate cap + dedup bound request volume from a tight error loop; server
  batch-size limit (`413`) and Pydantic `max_length` are the backstop.

## Testing

- **Server (pytest):**
  - endpoint reachable without a bearer token (auth-exempt).
  - valid batch → `204`; structlog emits one record per event at the mapped
    level with the expected structured fields. **Log capture pattern:** mirror
    the repo's existing structlog tests (`tests/test_structured_logging.py`) —
    call `setup_logging(log_format="json")` and read JSON lines from `capsys`,
    NOT pytest `caplog`. structlog uses `cache_logger_on_first_use=True` and is
    only routed through stdlib once `setup_logging` runs, so a bare
    `caplog.at_level(...)` does not reliably capture these records.
  - oversized batch (> 50 events) → `413`.
  - field truncation/redaction applied; `stack`/`component_stack` survive full
    (not truncated).
- **Client (vitest):**
  - buffering + flush on interval, on size threshold, and on `pagehide`
    (fake timers; mocked `fetch` and `navigator.sendBeacon`).
  - dedup collapses duplicate events and increments `count`.
  - rate cap drops beyond the limit and emits a single marker.
  - **loop-prevention:** a `console.error` triggered from inside the reporter
    does not recurse.
  - `ErrorBoundary` reports on catch; `api.ts` reports on `ApiError`.

## Out of scope (YAGNI)

- Source-map de-minification of production stack traces.
- A `client_logs` DB table / queryable error-history UI page.
- Cross-session analytics / aggregation.

All of the above can be layered on top of the logged events later.

## Files touched

New:
- `src/workbench/api/client_logs.py`
- `ui/src/lib/error-reporter.ts`
- tests: `tests/` (server) + `ui/src/lib/error-reporter.test.ts`

Modified:
- `src/workbench/runtime/app.py` (register router)
- `src/workbench/runtime/auth.py` (exempt path)
- `src/workbench/telemetry/privacy.py` (`NO_TRUNCATE_KEYS` += `component_stack`; `stack` already present)
- `ui/src/main.tsx` (install)
- `ui/src/components/ErrorBoundary.tsx` (`componentDidCatch`)
- `ui/src/lib/api.ts` (report on `ApiError`)
- `src/workbench/api/README.md` (document the new route module)
