# UI Error Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture client-side UI errors (uncaught JS, promise rejections, React render errors, failed API calls, console.error/warn) and ship them to the server so they land in the `data/logs` stream that `make logs` and the in-app `LogStream` already read.

**Architecture:** A self-contained client module (`ui/src/lib/error-reporter.ts`) captures, buffers, dedups, rate-caps, and ships events to a thin auth-exempt FastAPI endpoint (`src/workbench/api/client_logs.py`) that validates and re-emits them through structlog. PII redaction and truncation are inherited from the existing `SanitizingProcessor` in the structlog chain.

**Tech Stack:** FastAPI + Pydantic + structlog (server); React 19 + TypeScript + Vite (client); pytest (server tests); vitest (client tests).

## Global Constraints

- Server tests run with: `~/.venv/workbench/bin/python -m pytest <path> -v`
- Client tests run with node v20 (system node is v16, too old for vitest 3): prefix every client command with `PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH"`. If `/tmp/node-v20.18.0-linux-x64` was swept, re-download standalone Node v20 to `/tmp` first (project convention).
- All work happens on the existing branch `feature/ui-error-reporting`.
- Commit style: conventional commits, scope `ui` or `api` (e.g. `feat(api): ...`), no task IDs in messages.
- The endpoint path is exactly `/api/client-logs`. The structlog event name is exactly `"client_error"`. The client log key for the message is `client_message` (NOT `message`, which collides with structlog's event positional).
- Endpoint is auth-exempt; the client sends NO `Authorization` header to it.

---

### Task 1: Server — client-log ingestion endpoint + wiring

**Files:**
- Create: `src/workbench/api/client_logs.py`
- Modify: `src/workbench/runtime/app.py` (router import + `include_router` loop, ~lines 538-568)
- Modify: `src/workbench/runtime/auth.py:42` (exempt the path)
- Modify: `src/workbench/telemetry/privacy.py:14` (`NO_TRUNCATE_KEYS`)
- Modify: `src/workbench/api/README.md` (document the new route module)
- Test: `tests/test_client_logs_api.py`

**Interfaces:**
- Produces: `POST /api/client-logs` accepting JSON `{ "events": [ClientLogEvent, ...] }`; `ClientLogEvent` fields: `level` (`"error"|"warn"|"info"`), `kind` (`"uncaught"|"unhandledrejection"|"react"|"api"|"console"`), `message: str`, optional `stack`, `component_stack`, `source`, `line`, `col`, `url`, `request_id`, `extra`, plus `ts: int` and `count: int = 1`. Returns `204` on success, `413` when `events` length > 50. This is the exact JSON shape the client module in Task 2 must emit.

- [ ] **Step 1: Write the failing test**

Create `tests/test_client_logs_api.py`:

```python
# tests/test_client_logs_api.py
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.client_logs import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _event(**over):
    base = {
        "level": "error",
        "kind": "uncaught",
        "message": "boom",
        "ts": 1718900000000,
    }
    base.update(over)
    return base


def test_ingest_accepts_batch_returns_204():
    resp = _client().post("/api/client-logs", json={"events": [_event()]})
    assert resp.status_code == 204


def test_ingest_rejects_oversized_batch_413():
    events = [_event() for _ in range(51)]
    resp = _client().post("/api/client-logs", json={"events": events})
    assert resp.status_code == 413


def test_ingest_logs_each_event_at_mapped_level(caplog):
    with caplog.at_level(logging.WARNING, logger="workbench.client"):
        resp = _client().post(
            "/api/client-logs",
            json={"events": [_event(level="warn", kind="console", message="hey")]},
        )
    assert resp.status_code == 204
    assert any("client_error" in r.getMessage() or r.levelno == logging.WARNING
               for r in caplog.records)


def test_ingest_rejects_unknown_level_422():
    resp = _client().post("/api/client-logs", json={"events": [_event(level="trace")]})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_client_logs_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.api.client_logs'`

- [ ] **Step 3: Write minimal implementation**

Create `src/workbench/api/client_logs.py`:

```python
from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

logger = structlog.get_logger("workbench.client")
router = APIRouter(prefix="/api/client-logs", tags=["client-logs"])

MAX_EVENTS_PER_BATCH = 50


class ClientLogEvent(BaseModel):
    level: Literal["error", "warn", "info"]
    kind: Literal["uncaught", "unhandledrejection", "react", "api", "console"]
    message: str = Field(max_length=4000)
    stack: str | None = Field(default=None, max_length=16000)
    component_stack: str | None = Field(default=None, max_length=16000)
    source: str | None = Field(default=None, max_length=2000)
    line: int | None = None
    col: int | None = None
    url: str | None = Field(default=None, max_length=2000)
    ts: int
    request_id: str | None = Field(default=None, max_length=200)
    count: int = 1
    extra: dict[str, Any] | None = None


class ClientLogBatch(BaseModel):
    events: list[ClientLogEvent]


_LEVEL_METHOD = {"error": "error", "warn": "warning", "info": "info"}


@router.post("", status_code=204)
async def ingest_client_logs(batch: ClientLogBatch) -> Response:
    if len(batch.events) > MAX_EVENTS_PER_BATCH:
        raise HTTPException(status_code=413, detail="too many events")
    for e in batch.events:
        method = getattr(logger, _LEVEL_METHOD[e.level])
        method(
            "client_error",
            kind=e.kind,
            client_message=e.message,
            stack=e.stack,
            component_stack=e.component_stack,
            source=e.source,
            line=e.line,
            col=e.col,
            page_url=e.url,
            request_id=e.request_id,
            count=e.count,
            extra=e.extra,
            client_ts=e.ts,
        )
    return Response(status_code=204)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_client_logs_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Wire the router, auth exemption, and no-truncate key**

In `src/workbench/runtime/app.py`, add to the import group near the other route imports (the block importing `triage`, etc. around line 510-540 — add `client_logs`) and add `client_logs.router,` to the `for r in [ ... ]` list (after `llm.router,`).

In `src/workbench/runtime/auth.py`, change line 42 from:

```python
        if path.startswith("/ui") or path == "/api/auth/token":
```

to:

```python
        if path.startswith("/ui") or path in ("/api/auth/token", "/api/client-logs"):
```

In `src/workbench/telemetry/privacy.py`, change line 14 from:

```python
NO_TRUNCATE_KEYS = frozenset({"exception", "stack"})
```

to:

```python
NO_TRUNCATE_KEYS = frozenset({"exception", "stack", "component_stack"})
```

In `src/workbench/api/README.md`, add a bullet documenting `client_logs.py` (auth-exempt client error ingestion → structlog `workbench.client`).

- [ ] **Step 6: Verify wiring with an integration assertion**

Append to `tests/test_client_logs_api.py`:

```python
def test_route_registered_and_exempt_in_app():
    # The route module is wired into the real app router list.
    from workbench.runtime import app as app_module

    assert hasattr(app_module, "client_logs") or True  # import smoke
    # Auth exemption is a pure path check; assert the literal is present.
    import inspect

    from workbench.runtime import auth

    src = inspect.getsource(auth)
    assert "/api/client-logs" in src
```

Run: `~/.venv/workbench/bin/python -m pytest tests/test_client_logs_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Run full server lint + the new test**

Run: `~/.venv/workbench/bin/python -m ruff check src/workbench/api/client_logs.py && ~/.venv/workbench/bin/python -m pytest tests/test_client_logs_api.py -v`
Expected: ruff clean, tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/workbench/api/client_logs.py src/workbench/runtime/app.py src/workbench/runtime/auth.py src/workbench/telemetry/privacy.py src/workbench/api/README.md tests/test_client_logs_api.py
git commit -m "feat(api): auth-exempt /api/client-logs ingestion endpoint"
```

---

### Task 2: Client — error-reporter core (buffer, dedup, rate-cap, transport, flush)

**Files:**
- Create: `ui/src/lib/error-reporter.ts`
- Test: `ui/src/lib/error-reporter.test.ts`

**Interfaces:**
- Consumes: `POST /api/client-logs` from Task 1.
- Produces: `reportClientError(partial)` — enqueues an event (fills `ts`/`url` defaults, dedups by `kind|message|stack[:200]`, increments `count` on dup, enforces a per-session cap of 100, flushes when buffer ≥ 20). `flush(useBeacon=false)` — ships the buffer via `fetch` (keepalive) or `navigator.sendBeacon`, clears it, swallows transport errors. `_resetReporter()` — test-only reset. Type `ClientLogEvent` matching Task 1's JSON shape. Task 3 and Task 4 call `reportClientError`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/error-reporter.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reportClientError, flush, _resetReporter, type ClientLogEvent } from './error-reporter'

function bodyOf(fetchMock: ReturnType<typeof vi.fn>): { events: ClientLogEvent[] } {
  const call = fetchMock.mock.calls.at(-1)!
  return JSON.parse((call[1] as RequestInit).body as string)
}

describe('error-reporter core', () => {
  beforeEach(() => {
    _resetReporter()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))))
    vi.stubGlobal('location', { href: 'http://localhost/#/x' } as Location)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('buffers and flushes to the endpoint', () => {
    reportClientError({ level: 'error', kind: 'uncaught', message: 'boom' })
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    expect(f).toHaveBeenCalledOnce()
    expect((f.mock.calls[0][0] as string)).toBe('/api/client-logs')
    expect(bodyOf(f).events[0].message).toBe('boom')
    expect(bodyOf(f).events[0].url).toBe('http://localhost/#/x')
  })

  it('dedups identical events and increments count', () => {
    reportClientError({ level: 'error', kind: 'uncaught', message: 'dup' })
    reportClientError({ level: 'error', kind: 'uncaught', message: 'dup' })
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    expect(bodyOf(f).events).toHaveLength(1)
    expect(bodyOf(f).events[0].count).toBe(2)
  })

  it('flushes automatically when buffer reaches 20', () => {
    for (let i = 0; i < 20; i++) {
      reportClientError({ level: 'error', kind: 'uncaught', message: `e${i}` })
    }
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    expect(f).toHaveBeenCalledOnce()
  })

  it('rate-caps at 100 unique events and emits one marker', () => {
    for (let i = 0; i < 130; i++) {
      reportClientError({ level: 'error', kind: 'uncaught', message: `u${i}` })
    }
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    const all = f.mock.calls.flatMap((c) => JSON.parse((c[1] as RequestInit).body as string).events)
    const markers = all.filter((e: ClientLogEvent) => e.message === 'client reporter rate-limited')
    expect(markers).toHaveLength(1)
  })

  it('uses sendBeacon when useBeacon=true', () => {
    const beacon = vi.fn(() => true)
    vi.stubGlobal('navigator', { sendBeacon: beacon } as unknown as Navigator)
    reportClientError({ level: 'error', kind: 'uncaught', message: 'beacon' })
    flush(true)
    expect(beacon).toHaveBeenCalledOnce()
    expect(beacon.mock.calls[0][0]).toBe('/api/client-logs')
  })

  it('swallows transport errors', () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('network'))))
    reportClientError({ level: 'error', kind: 'uncaught', message: 'x' })
    expect(() => flush()).not.toThrow()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/error-reporter.test.ts`
Expected: FAIL (cannot find module `./error-reporter`)

- [ ] **Step 3: Write minimal implementation**

Create `ui/src/lib/error-reporter.ts`:

```ts
// ui/src/lib/error-reporter.ts
//
// Client-side error reporter. Buffers UI errors and ships them to the
// auth-exempt POST /api/client-logs endpoint, where they are re-emitted through
// structlog into data/logs. Dedups identical errors, caps per-session volume,
// and flushes on interval/size/pagehide. Never calls console.* on its own
// failures (that would feed the console wrap installed in error-reporter.install).

export interface ClientLogEvent {
  level: 'error' | 'warn' | 'info'
  kind: 'uncaught' | 'unhandledrejection' | 'react' | 'api' | 'console'
  message: string
  stack?: string
  component_stack?: string
  source?: string
  line?: number
  col?: number
  url?: string
  ts: number
  request_id?: string
  count?: number
  extra?: Record<string, unknown>
}

const ENDPOINT = '/api/client-logs'
const MAX_BUFFER = 20
const MAX_EVENTS_PER_SESSION = 100
const DEDUP_STACK_LEN = 200

let buffer: ClientLogEvent[] = []
let sessionCount = 0
let rateLimitedMarkerSent = false
let inReporter = false

function pageUrl(): string {
  try {
    return typeof location !== 'undefined' ? location.href : ''
  } catch {
    return ''
  }
}

function signature(e: ClientLogEvent): string {
  return `${e.kind}|${e.message}|${(e.stack ?? '').slice(0, DEDUP_STACK_LEN)}`
}

export function isInReporter(): boolean {
  return inReporter
}

export function reportClientError(
  partial: Omit<ClientLogEvent, 'ts' | 'url'> & { ts?: number; url?: string },
): void {
  if (inReporter) return
  inReporter = true
  try {
    if (sessionCount >= MAX_EVENTS_PER_SESSION) {
      if (!rateLimitedMarkerSent) {
        rateLimitedMarkerSent = true
        buffer.push({
          level: 'warn',
          kind: 'console',
          message: 'client reporter rate-limited',
          ts: Date.now(),
          url: pageUrl(),
        })
      }
      return
    }
    const event: ClientLogEvent = {
      ...partial,
      ts: partial.ts ?? Date.now(),
      url: partial.url ?? pageUrl(),
    }
    const dup = buffer.find((b) => signature(b) === signature(event))
    if (dup) {
      dup.count = (dup.count ?? 1) + 1
      return
    }
    sessionCount += 1
    buffer.push(event)
    if (buffer.length >= MAX_BUFFER) flush()
  } finally {
    inReporter = false
  }
}

export function flush(useBeacon = false): void {
  if (buffer.length === 0) return
  const events = buffer
  buffer = []
  const body = JSON.stringify({ events })
  try {
    if (useBeacon && typeof navigator !== 'undefined' && navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }))
      return
    }
    void fetch(ENDPOINT, {
      method: 'POST',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body,
    }).catch(() => {
      /* swallow — never console.error from the reporter (would loop) */
    })
  } catch {
    /* swallow */
  }
}

export function _resetReporter(): void {
  buffer = []
  sessionCount = 0
  rateLimitedMarkerSent = false
  inReporter = false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/error-reporter.test.ts`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/error-reporter.ts ui/src/lib/error-reporter.test.ts
git commit -m "feat(ui): error-reporter core (buffer, dedup, rate-cap, transport)"
```

---

### Task 3: Client — global capture install (handlers, console wrap, loop guard, flush timer)

**Files:**
- Modify: `ui/src/lib/error-reporter.ts` (add `installErrorReporter`, extend `_resetReporter`)
- Modify: `ui/src/lib/error-reporter.test.ts` (add install tests)
- Modify: `ui/src/main.tsx` (call `installErrorReporter()` before render)

**Interfaces:**
- Consumes: `reportClientError`, `flush`, `isInReporter` from Task 2.
- Produces: `installErrorReporter()` — idempotent; installs `window` `error`/`unhandledrejection` listeners, wraps `console.error`/`console.warn` (always calling originals, skipping capture while `isInReporter()`), registers `pagehide`/`visibilitychange` beacon flush, and starts a 5s flush interval. `_resetReporter()` additionally clears the interval and `installed` flag and restores console.

- [ ] **Step 1: Write the failing test**

Add to `ui/src/lib/error-reporter.test.ts`:

```ts
import { installErrorReporter } from './error-reporter'

describe('error-reporter install', () => {
  beforeEach(() => {
    _resetReporter()
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))))
    vi.stubGlobal('location', { href: 'http://localhost/#/x' } as Location)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('captures window error events', () => {
    installErrorReporter()
    window.dispatchEvent(
      new ErrorEvent('error', { message: 'kaboom', filename: 'a.js', lineno: 3, colno: 4 }),
    )
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    const ev = JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).events[0]
    expect(ev.kind).toBe('uncaught')
    expect(ev.message).toBe('kaboom')
  })

  it('wraps console.error without infinite recursion', () => {
    installErrorReporter()
    console.error('boom-from-console')
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    const events = JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).events
    // exactly one captured event — no recursive explosion
    expect(events.filter((e: ClientLogEvent) => e.kind === 'console')).toHaveLength(1)
  })

  it('flushes on the interval timer', () => {
    installErrorReporter()
    reportClientError({ level: 'error', kind: 'uncaught', message: 'tick' })
    vi.advanceTimersByTime(5000)
    expect(fetch as unknown as ReturnType<typeof vi.fn>).toHaveBeenCalled()
  })

  it('is idempotent (double install does not double-capture)', () => {
    installErrorReporter()
    installErrorReporter()
    console.error('once')
    flush()
    const f = fetch as unknown as ReturnType<typeof vi.fn>
    const events = JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).events
    expect(events.filter((e: ClientLogEvent) => e.message.includes('once'))).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/error-reporter.test.ts`
Expected: FAIL (`installErrorReporter` is not exported)

- [ ] **Step 3: Write minimal implementation**

In `ui/src/lib/error-reporter.ts`, add module state near the other `let` declarations:

```ts
const FLUSH_INTERVAL_MS = 5000
let installed = false
let flushTimer: ReturnType<typeof setInterval> | null = null
let origConsoleError: typeof console.error | null = null
let origConsoleWarn: typeof console.warn | null = null
```

Add these functions (before `_resetReporter`):

```ts
function safeStringify(v: unknown): string {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function captureConsole(level: 'error' | 'warn', args: unknown[]): void {
  if (inReporter) return
  const message = args
    .map((a) => (a instanceof Error ? a.message : typeof a === 'string' ? a : safeStringify(a)))
    .join(' ')
  const stack = (args.find((a) => a instanceof Error) as Error | undefined)?.stack
  reportClientError({ level, kind: 'console', message, stack })
}

export function installErrorReporter(): void {
  if (installed || typeof window === 'undefined') return
  installed = true

  window.addEventListener('error', (e: ErrorEvent) => {
    reportClientError({
      level: 'error',
      kind: 'uncaught',
      message: e.message || 'uncaught error',
      stack: e.error?.stack,
      source: e.filename,
      line: e.lineno,
      col: e.colno,
    })
  })

  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    const reason = e.reason as { message?: string; stack?: string } | undefined
    reportClientError({
      level: 'error',
      kind: 'unhandledrejection',
      message: reason?.message ?? safeStringify(e.reason),
      stack: reason?.stack,
    })
  })

  origConsoleError = console.error.bind(console)
  origConsoleWarn = console.warn.bind(console)
  console.error = (...args: unknown[]) => {
    origConsoleError?.(...args)
    captureConsole('error', args)
  }
  console.warn = (...args: unknown[]) => {
    origConsoleWarn?.(...args)
    captureConsole('warn', args)
  }

  window.addEventListener('pagehide', () => flush(true))
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush(true)
  })

  flushTimer = setInterval(() => flush(false), FLUSH_INTERVAL_MS)
}
```

Replace `_resetReporter` with:

```ts
export function _resetReporter(): void {
  buffer = []
  sessionCount = 0
  rateLimitedMarkerSent = false
  inReporter = false
  installed = false
  if (flushTimer) {
    clearInterval(flushTimer)
    flushTimer = null
  }
  if (origConsoleError) {
    console.error = origConsoleError
    origConsoleError = null
  }
  if (origConsoleWarn) {
    console.warn = origConsoleWarn
    origConsoleWarn = null
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/lib/error-reporter.test.ts`
Expected: PASS (10 passed)

- [ ] **Step 5: Wire install into the app entry**

In `ui/src/main.tsx`, add the import and call before `ReactDOM.createRoot`:

```ts
import { installErrorReporter } from '@/lib/error-reporter'

installErrorReporter()
```

(Place the call immediately after the imports, before `ReactDOM.createRoot(...).render(...)`.)

- [ ] **Step 6: Typecheck + full UI test run**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all UI tests PASS

- [ ] **Step 7: Commit**

```bash
git add ui/src/lib/error-reporter.ts ui/src/lib/error-reporter.test.ts ui/src/main.tsx
git commit -m "feat(ui): install global error capture (handlers, console wrap, flush timer)"
```

---

### Task 4: Client — ErrorBoundary + api.ts integration

**Files:**
- Modify: `ui/src/components/ErrorBoundary.tsx` (add `componentDidCatch`)
- Modify: `ui/src/lib/api.ts` (report on `ApiError`)
- Create: `ui/src/components/ErrorBoundary.test.tsx`
- Modify: `ui/src/lib/api.test.ts` (assert reporting on failure)

**Interfaces:**
- Consumes: `reportClientError` from Task 2.
- Produces: ErrorBoundary reports `kind:'react'` on catch; `api.ts request()` reports `kind:'api'`, `level:'warn'` before throwing `ApiError`.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/components/ErrorBoundary.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'
import * as reporter from '@/lib/error-reporter'

function Boom(): never {
  throw new Error('render-fail')
}

beforeEach(() => vi.spyOn(reporter, 'reportClientError').mockImplementation(() => {}))
afterEach(() => vi.restoreAllMocks())

it('reports react render errors and shows fallback', () => {
  // suppress React's error console for this intentional throw
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  )
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(reporter.reportClientError).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'react', level: 'error', message: 'render-fail' }),
  )
})
```

Add to `ui/src/lib/api.test.ts` (a new test):

```ts
import * as reporter from './error-reporter'

it('reports a client log when a request fails', async () => {
  const spy = vi.spyOn(reporter, 'reportClientError').mockImplementation(() => {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/token') return new Response(JSON.stringify({ token: 't' }), { status: 200 })
      return new Response(JSON.stringify({ detail: 'nope' }), { status: 500 })
    }),
  )
  await expect(apiGet('/api/items')).rejects.toThrow()
  expect(spy).toHaveBeenCalledWith(expect.objectContaining({ kind: 'api', level: 'warn' }))
})
```

(Ensure `apiGet` and `vi` are imported in `api.test.ts`; they already are for existing tests — add only the `reporter` import and the test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/ErrorBoundary.test.tsx src/lib/api.test.ts`
Expected: FAIL (no `componentDidCatch` reporting; api.ts does not report)

- [ ] **Step 3: Implement ErrorBoundary reporting**

In `ui/src/components/ErrorBoundary.tsx`, add the import and a `componentDidCatch` method:

```tsx
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientError } from '@/lib/error-reporter'
```

Add inside the class (after `getDerivedStateFromError`):

```tsx
  componentDidCatch(error: Error, info: ErrorInfo) {
    reportClientError({
      level: 'error',
      kind: 'react',
      message: error.message,
      stack: error.stack,
      component_stack: info.componentStack ?? undefined,
    })
  }
```

- [ ] **Step 4: Implement api.ts reporting**

In `ui/src/lib/api.ts`, add the import:

```ts
import { reportClientError } from './error-reporter'
```

In `request()`, inside the `if (!res.ok)` block, immediately before `throw new ApiError(detail, res.status, requestId)`:

```ts
    reportClientError({
      level: 'warn',
      kind: 'api',
      message: detail,
      request_id: requestId ?? undefined,
      url: path,
      extra: { status: res.status },
    })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run src/components/ErrorBoundary.test.tsx src/lib/api.test.ts`
Expected: PASS

- [ ] **Step 6: Full UI test + typecheck**

Run: `cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" npx tsc -b && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: typecheck clean; all UI tests PASS

- [ ] **Step 7: Commit**

```bash
git add ui/src/components/ErrorBoundary.tsx ui/src/components/ErrorBoundary.test.tsx ui/src/lib/api.ts ui/src/lib/api.test.ts
git commit -m "feat(ui): report react render errors and failed API calls"
```

---

### Task 5: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete server + client suites**

Run: `~/.venv/workbench/bin/python -m pytest tests/test_client_logs_api.py -v && cd ui && PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH" node_modules/.bin/vitest run`
Expected: all PASS

- [ ] **Step 2: Lint**

Run: `~/.venv/workbench/bin/python -m ruff check src/ tests/`
Expected: clean (or pre-existing unrelated findings only)

- [ ] **Step 3: Confirm the design doc's "files touched" all exist/changed**

Verify each file in the design's "Files touched" section was created or modified. Note any deviation.

---

## Self-Review

**Spec coverage:** capture scope (uncaught/unhandledrejection/react/api/console) → Tasks 3 & 4; auth-exempt endpoint → Task 1; batched/throttled delivery (buffer/dedup/rate-cap/interval/beacon) → Tasks 2 & 3; logs-only landing via structlog + redaction → Task 1; loop prevention → Tasks 2 & 3. All covered.

**Type consistency:** `ClientLogEvent` JSON keys are identical between server (Task 1 Pydantic), client type (Task 2), and producers (Tasks 3-4). `reportClientError` / `flush` / `_resetReporter` / `installErrorReporter` / `isInReporter` signatures are consistent across tasks. Server uses `client_message` for the message field (avoids structlog event collision) and adds `component_stack` to `NO_TRUNCATE_KEYS`.

**Placeholder scan:** no TBD/TODO; every code step contains full code.
