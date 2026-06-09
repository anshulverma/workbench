import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'
import { useTriageCard } from './useTriageCard'
import { _resetToken } from '@/lib/api'

const CARD = {
  id: 'c1',
  card_content: { content_schema: 'diff.v1', summary: 'adds retry', sections: { summary: 'adds retry' } },
  options: [{ label: 'Add P1', action: 'add_todo' }],
  relevance_score: 80,
  status: 'sent',
}

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
  _resetToken()
})
afterAll(() => server.close())

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return createElement(QueryClientProvider, { client }, children)
}

describe('useTriageCard', () => {
  it('fetches a single card by id', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    const { result } = renderHook(() => useTriageCard('c1'), { wrapper })
    await waitFor(() => expect(result.current.data?.id).toBe('c1'))
    expect(result.current.data?.card_content.content_schema).toBe('diff.v1')
  })

  it('surfaces an error for a 404', async () => {
    server.use(
      http.get('/api/triage/cards/missing', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    const { result } = renderHook(() => useTriageCard('missing'), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
