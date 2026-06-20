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
const FLUSH_INTERVAL_MS = 5000

let buffer: ClientLogEvent[] = []
let sessionCount = 0
let rateLimitedMarkerSent = false
let inReporter = false
let installed = false
let flushTimer: ReturnType<typeof setInterval> | null = null
let origConsoleError: typeof console.error | null = null
let origConsoleWarn: typeof console.warn | null = null
let errorHandler: ((e: ErrorEvent) => void) | null = null
let rejectionHandler: ((e: PromiseRejectionEvent) => void) | null = null
let pagehideHandler: (() => void) | null = null
let visibilitychangeHandler: (() => void) | null = null

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

export function installErrorReporter(): void {
  if (installed || typeof window === 'undefined') return
  installed = true

  errorHandler = (e: ErrorEvent) => {
    reportClientError({
      level: 'error',
      kind: 'uncaught',
      message: e.message || 'uncaught error',
      stack: e.error?.stack,
      source: e.filename,
      line: e.lineno,
      col: e.colno,
    })
  }
  window.addEventListener('error', errorHandler)

  rejectionHandler = (e: PromiseRejectionEvent) => {
    const reason = e.reason as { message?: string; stack?: string } | undefined
    reportClientError({
      level: 'error',
      kind: 'unhandledrejection',
      message: reason?.message ?? safeStringify(e.reason),
      stack: reason?.stack,
    })
  }
  window.addEventListener('unhandledrejection', rejectionHandler)

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

  pagehideHandler = () => flush(true)
  window.addEventListener('pagehide', pagehideHandler)
  visibilitychangeHandler = () => {
    if (document.visibilityState === 'hidden') flush(true)
  }
  document.addEventListener('visibilitychange', visibilitychangeHandler)

  flushTimer = setInterval(() => flush(false), FLUSH_INTERVAL_MS)
}

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
  if (typeof window !== 'undefined') {
    if (errorHandler) {
      window.removeEventListener('error', errorHandler)
      errorHandler = null
    }
    if (rejectionHandler) {
      window.removeEventListener('unhandledrejection', rejectionHandler)
      rejectionHandler = null
    }
    if (pagehideHandler) {
      window.removeEventListener('pagehide', pagehideHandler)
      pagehideHandler = null
    }
  }
  if (typeof document !== 'undefined' && visibilitychangeHandler) {
    document.removeEventListener('visibilitychange', visibilitychangeHandler)
    visibilitychangeHandler = null
  }
}
