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
