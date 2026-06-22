// Search page tests — search with dialog, type-to-search, kind filters.

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

// API-shaped fixtures (snake_case, integer id)
const RESULT = {
  id: 11,
  source_type: 'diff',
  summary: 'crashy item',
  status: 'pending_triage',
  priority: 'P2',
  tags: [],
  llm_summary: 'matters',
  enriched_context: {},
  processing_log: [],
  verdict: { action: 'triage' },
  path: null,
}

const TASKS_RESULT = {
  id: 22,
  source_type: 'meta_tasks',
  summary: 'important task',
  status: 'pending_triage',
  priority: 'P1',
  tags: ['urgent'],
  llm_summary: 'critical work',
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
    http.get('/api/items/by-id/:id', () => HttpResponse.json(RESULT)),
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
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
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
  it('shows recent items before any query is typed', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: '', results: [RESULT], total: 1 }),
      ),
    )
    renderSearch()
    // No typing: the no-query default renders the recent item list.
    expect(await screen.findByText(RESULT.summary)).toBeInTheDocument()
  })

  it('lists results and opens the dialog on row click', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: 'cr', results: [RESULT], total: 1 }),
      ),
      http.get('/api/items/by-id/11', () => HttpResponse.json(RESULT)),
    )
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'cr')
    await waitFor(() => expect(screen.getByText('crashy item')).toBeInTheDocument())
    await userEvent.click(screen.getByText('crashy item'))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    expect(screen.getByText('matters')).toBeInTheDocument()
  })

  it('filters results by kind buttons', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: 'ab', results: [RESULT, TASKS_RESULT], total: 2 }),
      ),
    )
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'ab')
    await waitFor(() => {
      expect(screen.getByText('crashy item')).toBeInTheDocument()
      expect(screen.getByText('important task')).toBeInTheDocument()
    })

    // Filter by Tasks (meta_tasks)
    await userEvent.click(screen.getByRole('button', { name: 'Tasks' }))
    await waitFor(() => {
      expect(screen.queryByText('crashy item')).not.toBeInTheDocument()
      expect(screen.getByText('important task')).toBeInTheDocument()
    })
  })

  it('clears search with the clear button', async () => {
    renderSearch()
    const input = screen.getByLabelText('Search items')
    await userEvent.type(input, 'x')
    await waitFor(() => {
      expect(input).toHaveValue('x')
    })

    const clearBtn = screen.getByLabelText('Clear')
    await userEvent.click(clearBtn)
    expect(input).toHaveValue('')
  })

  it('shows empty state when no results match', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json({ q: 'xyz', results: [], total: 0 }),
      ),
    )
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'xyz')
    await waitFor(() => {
      expect(screen.getByText('// No items match your search')).toBeInTheDocument()
    })
  })

  it('renders the error state', async () => {
    server.use(
      http.get('/api/items/search', () =>
        HttpResponse.json(
          { detail: 'Internal Server Error' },
          { status: 500 },
        ),
      ),
    )
    renderSearch()
    await userEvent.type(screen.getByLabelText('Search items'), 'er')
    await waitFor(() => {
      expect(screen.getByTestId('search-error')).toBeInTheDocument()
    })
  })

  it('shows kind filter buttons', () => {
    renderSearch()
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Diffs' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Docs' })).toBeInTheDocument()
  })
})
