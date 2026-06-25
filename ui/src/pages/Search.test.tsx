// Search page tests — two-pane master/detail. A row click SELECTS (local state,
// no ?item= dialog) and swaps the inline detail panel; the first result
// auto-selects on load. Both useItemsSearch (list) and useItemDetail (detail)
// are mocked via msw.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Search } from './Search'
import { ItemDetailDialog } from '@/components/ItemDetailDialog'
import { _resetToken } from '@/lib/api'

// API-shaped fixtures (snake_case, integer id). `kind` is derived from
// source_type by the search adapter, so these must be valid ItemKinds.
const DIFF = {
  id: 11,
  source_type: 'diff',
  summary: 'crashy item',
  status: 'pending_triage',
  priority: 'P2',
  tags: [],
  llm_summary: 'diff matters',
  enriched_context: {},
  processing_log: [],
  verdict: { action: 'triage' },
  path: null,
}

const EMAIL = {
  id: 22,
  source_type: 'email',
  summary: 'inbox note',
  status: 'pending_triage',
  priority: 'P1',
  tags: ['urgent'],
  llm_summary: 'email matters',
  enriched_context: {},
  processing_log: [],
  verdict: { action: 'triage' },
  path: null,
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/items/search', () =>
      HttpResponse.json({ q: '', results: [], total: 0 }),
    ),
    http.get('/api/items/by-id/:id', ({ params }) =>
      HttpResponse.json(params.id === '22' ? EMAIL : DIFF),
    ),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  server.resetHandlers()
  _resetToken()
})
afterAll(() => server.close())

function renderSearch() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/search']}>
        <Search />
        <ItemDetailDialog />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Search page', () => {
  it('shows the loading state before results arrive', () => {
    renderSearch()
    // Query is pending on first paint.
    expect(screen.getByTestId('search-loading')).toBeInTheDocument()
  })

  it('auto-selects the first result and renders its detail inline', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: '', results: [DIFF], total: 1 }),
      ),
    )
    renderSearch()
    // Detail panel resolves for the auto-selected first row (no click needed).
    expect(await screen.findByText('diff matters')).toBeInTheDocument()
    const row = document.getElementById('search-row-11')
    expect(row).toHaveAttribute('aria-selected', 'true')
  })

  it('selecting a row swaps the detail inline, without opening a dialog', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: '', results: [DIFF, EMAIL], total: 2 }),
      ),
    )
    renderSearch()
    // First result (diff) auto-selected.
    expect(await screen.findByText('diff matters')).toBeInTheDocument()

    // Click the email row → selects it and swaps the detail.
    await userEvent.click(screen.getByText('inbox note'))
    expect(await screen.findByText('email matters')).toBeInTheDocument()
    expect(document.getElementById('search-row-22')).toHaveAttribute('aria-selected', 'true')
    expect(document.getElementById('search-row-11')).toHaveAttribute('aria-selected', 'false')
    // No modal dialog — selection is local state, not the ?item= popup.
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('filters results by kind buttons', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: '', results: [DIFF, EMAIL], total: 2 }),
      ),
    )
    renderSearch()
    await waitFor(() => {
      expect(document.getElementById('search-row-11')).toBeInTheDocument()
      expect(document.getElementById('search-row-22')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Email' }))
    await waitFor(() => {
      expect(document.getElementById('search-row-11')).toBeNull()
      expect(document.getElementById('search-row-22')).toBeInTheDocument()
    })
  })

  it('clears the query with the clear button', async () => {
    renderSearch()
    const input = screen.getByLabelText('Search items')
    await userEvent.type(input, 'x')
    await waitFor(() => expect(input).toHaveValue('x'))

    await userEvent.click(screen.getByLabelText('Clear'))
    expect(input).toHaveValue('')
  })

  it('shows the empty state when no results match', async () => {
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'xyz')
    await waitFor(() =>
      expect(screen.getByText('// No items match your search')).toBeInTheDocument(),
    )
  })

  it('renders the error state', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ detail: 'Internal Server Error' }, { status: 500 }),
      ),
    )
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'er')
    await waitFor(() => expect(screen.getByTestId('search-error')).toBeInTheDocument())
  })

  it('shows the type-correct kind filter buttons', () => {
    renderSearch()
    for (const name of ['All', 'Diffs', 'Email', 'Meetings', 'Chat']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
  })
})
