import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, beforeAll, afterEach, afterAll } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { useItemDetail, useItemsSearch } from './useItemDetail'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const RICH = {
  id: 5,
  source_type: 'diff',
  summary: 'hi',
  status: 'pending_triage',
  priority: 'P2',
  tags: ['t'],
  llm_summary: 'why',
  enriched_context: {},
  processing_log: [],
  verdict: { action: 'triage', priority: 'P2', confidence: 1 },
  path: null,
}

describe('useItemDetail', () => {
  it('fetches and adapts a single item by id', async () => {
    server.use(http.get('/api/items/by-id/5', () => HttpResponse.json(RICH)))
    const { result } = renderHook(() => useItemDetail(5), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.kind).toBe('diff')
    expect(result.current.data!.tags).toEqual(['t'])
  })

  it('is disabled when id is null', () => {
    const { result } = renderHook(() => useItemDetail(null), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('useItemsSearch', () => {
  it('fetches recent items for an empty/short query (no enable gate)', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: '', results: [RICH], total: 1 }),
      ),
    )
    const { result } = renderHook(() => useItemsSearch(''), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!).toHaveLength(1)
  })

  it('fetches and adapts results when q>=2', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: 'hi', results: [RICH], total: 1 }),
      ),
    )
    const { result } = renderHook(() => useItemsSearch('hi'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!).toHaveLength(1)
    expect(result.current.data![0].id).toBe(5)
  })
})
