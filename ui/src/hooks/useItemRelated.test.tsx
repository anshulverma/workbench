import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useItemRelated } from './useItems'
import { _resetToken } from '@/lib/api'

const PAYLOAD = {
  path: '123',
  subtree: false,
  counts: { llm_call: 1, triage_card: 1 },
  groups: {
    llm_call: [{ entity_type: 'llm_call', id: 991, label: 'score_relevance · ok', at: '2026-06-18T15:02:11Z', href: '/llm/991' }],
    triage_card: [{ entity_type: 'triage_card', id: 5, label: 'card #5', at: '2026-06-18T15:00:00Z', href: null }],
  },
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/123/related', ({ request }) => {
    const url = new URL(request.url)
    return HttpResponse.json({ ...PAYLOAD, subtree: url.searchParams.get('subtree') === 'true' })
  }),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useItemRelated', () => {
  it('fetches /related and returns grouped entities', async () => {
    const { result } = renderHook(() => useItemRelated('123', false), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.counts.llm_call).toBe(1)
    expect(result.current.data!.groups.llm_call[0].href).toBe('/llm/991')
  })

  it('passes subtree=true', async () => {
    const { result } = renderHook(() => useItemRelated('123', true), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.subtree).toBe(true)
  })
})
