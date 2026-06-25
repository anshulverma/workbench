// useItemActions tests — verifies each ItemAction maps to the correct backend
// endpoint and that done/archive fire onAfterDismiss (priority/snooze do not).

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useItemActions } from './useItemActions'
import { _resetToken } from '@/lib/api'

const hits: string[] = []

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.post('/api/actions/:id/:action', ({ params }) => {
    hits.push(`${params.id}/${params.action}`)
    return HttpResponse.json({ ok: true })
  }),
)
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers()
  _resetToken()
  hits.length = 0
})
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useItemActions', () => {
  it('maps each action to its endpoint', async () => {
    const { result } = renderHook(() => useItemActions(), { wrapper })

    result.current.onAction(7, 'priority', 'P1')
    result.current.onAction(7, 'done')
    result.current.onAction(7, 'snooze')
    result.current.onAction(7, 'archive')
    result.current.onAction(7, 'delete') // delete → soft-archive

    await waitFor(() => expect(hits).toHaveLength(5))
    expect(hits).toContain('7/priority')
    expect(hits).toContain('7/done')
    expect(hits).toContain('7/snooze')
    expect(hits.filter((h) => h === '7/archive')).toHaveLength(2) // archive + delete
  })

  it('ignores a blank priority (no endpoint for "—")', async () => {
    const { result } = renderHook(() => useItemActions(), { wrapper })
    result.current.onAction(7, 'priority', '')
    // give any (incorrect) request a chance to land
    await new Promise((r) => setTimeout(r, 50))
    expect(hits).toHaveLength(0)
  })

  it('fires onAfterDismiss only for done and archive/delete', async () => {
    const onAfterDismiss = vi.fn()
    const { result } = renderHook(() => useItemActions({ onAfterDismiss }), { wrapper })

    result.current.onAction(7, 'priority', 'P1')
    result.current.onAction(7, 'snooze')
    await waitFor(() => expect(hits).toHaveLength(2))
    expect(onAfterDismiss).not.toHaveBeenCalled()

    result.current.onAction(9, 'done')
    result.current.onAction(9, 'archive')
    await waitFor(() => expect(onAfterDismiss).toHaveBeenCalledTimes(2))
    expect(onAfterDismiss).toHaveBeenCalledWith(9)
  })
})
