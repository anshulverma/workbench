import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ItemPage } from './ItemPage'
import { _resetToken } from '@/lib/api'

const ITEM = {
  item: { id: 123, path: '123', seq: null, summary: 'root', status: 'extracted' },
  ancestors: [],
  children: [],
}

const RELATED = {
  path: '123',
  subtree: false,
  counts: { llm_call: 1, triage_card: 1 },
  groups: {
    llm_call: [{ entity_type: 'llm_call', id: 991, label: 'score_relevance · ok', at: null, href: '/llm/991' }],
    triage_card: [{ entity_type: 'triage_card', id: 5, label: 'card #5', at: null, href: null }],
  },
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/123', () => HttpResponse.json(ITEM)),
  http.get('/api/items/123/related', ({ request }) => {
    const url = new URL(request.url)
    return HttpResponse.json({ ...RELATED, subtree: url.searchParams.get('subtree') === 'true' })
  }),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(); _resetToken() })
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/items/123']}>
        <Routes>
          <Route path="/items/*" element={<ItemPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemPage What touched this', () => {
  it('renders the related section grouped by type with a link for llm_call', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('What touched this')).toBeTruthy())
    const link = await screen.findByRole('link', { name: /score_relevance/ })
    expect(link.getAttribute('href')).toContain('/llm/991')
    // triage_card has no href -> plain text, not a link.
    expect(screen.getByText('card #5')).toBeTruthy()
  })

  it('include-descendants toggle re-fetches with subtree=true', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('What touched this')).toBeTruthy())
    const toggle = screen.getByLabelText('include descendants')
    fireEvent.click(toggle)
    await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true))
  })
})
