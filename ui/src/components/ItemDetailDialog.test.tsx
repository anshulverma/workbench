import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, beforeAll, afterEach, afterAll } from 'vitest'
import type { ReactNode } from 'react'
import { _resetToken } from '@/lib/api'
import { ItemDetailDialog } from './ItemDetailDialog'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function renderAt(initial: string, ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const RICH = {
  id: 5, source_type: 'diff', summary: 'Diff D5 fixing things is awaiting review',
  status: 'pending_triage',
  priority: 'P2', tags: ['t'], llm_summary: 'why it matters', enriched_context: {},
  processing_log: [], verdict: { action: 'triage' }, path: null,
}

describe('ItemDetailDialog', () => {
  it('is closed with no ?item param', () => {
    renderAt('/search', <ItemDetailDialog />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('opens and shows item detail when ?item=<id> is present', async () => {
    server.use(http.get('/api/items/by-id/5', () => HttpResponse.json(RICH)))
    renderAt('/search?item=5', <ItemDetailDialog />)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    // Title is split into emphasis segments; the diff ref and status clause are
    // bold and " by you" is appended for diffs.
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
        'Diff D5 fixing things is awaiting review by you',
      ),
    )
    expect(screen.getByText('why it matters')).toBeInTheDocument()
  })

  it('shows "item not found" on 404', async () => {
    server.use(
      http.get('/api/items/by-id/9', () =>
        new HttpResponse(JSON.stringify({ detail: 'Item not found' }), { status: 404 }),
      ),
    )
    renderAt('/search?item=9', <ItemDetailDialog />)
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument())
  })
})
