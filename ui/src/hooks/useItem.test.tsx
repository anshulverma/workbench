import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useItem } from './useItems'
import { _resetToken } from '@/lib/api'

const PAYLOAD = {
  item: { id: 1, path: '1', seq: null, summary: 'root', status: 'extracted' },
  ancestors: [],
  children: [
    { id: 2, path: '1.1', seq: 1, summary: 'c1', status: 'active', priority: 'P2', has_children: true },
  ],
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(PAYLOAD)),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useItem', () => {
  it('fetches /api/items/:path and returns item + children', async () => {
    const { result } = renderHook(() => useItem('1'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data!.item.path).toBe('1')
    expect(result.current.data!.children[0].path).toBe('1.1')
    expect(result.current.data!.children[0].has_children).toBe(true)
  })
})
