import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  reportClientError,
  flush,
  _resetReporter,
  installErrorReporter,
  type ClientLogEvent,
} from './error-reporter'

function bodyOf(fetchMock: ReturnType<typeof vi.fn>): { events: ClientLogEvent[] } {
  const call = fetchMock.mock.calls.at(-1)
  if (!call) throw new Error('No fetch calls found')
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
    expect((beacon.mock.calls as unknown[][])[0][0]).toBe('/api/client-logs')
  })

  it('swallows transport errors', () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('network'))))
    reportClientError({ level: 'error', kind: 'uncaught', message: 'x' })
    expect(() => flush()).not.toThrow()
  })
})

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
