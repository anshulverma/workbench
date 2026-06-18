import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ItemPage } from './ItemPage'
import { _resetToken } from '@/lib/api'

const ROOT = {
  item: { id: 1, path: '1', seq: null, summary: 'root diff', status: 'extracted' },
  ancestors: [],
  children: [
    { id: 2, path: '1.1', seq: 1, summary: 'extracted A', status: 'active', priority: 'P2', has_children: true },
    { id: 3, path: '1.2', seq: 2, summary: 'extracted B', status: 'dropped', priority: 'P3', has_children: false },
  ],
}
const ACTION = {
  item: { id: 4, path: '1.1.1', seq: 1, summary: 'ping reviewer', status: 'active' },
  ancestors: [
    { id: 1, path: '1', summary: 'root diff', status: 'extracted' },
    { id: 2, path: '1.1', summary: 'extracted A', status: 'active' },
  ],
  children: [],
}
const CHILD11 = {
  item: { id: 2, path: '1.1', seq: 1, summary: 'extracted A', status: 'active' },
  ancestors: [{ id: 1, path: '1', summary: 'root diff', status: 'extracted' }],
  children: [
    { id: 4, path: '1.1.1', seq: 1, summary: 'ping reviewer', status: 'active', priority: 'P2', has_children: false },
  ],
}

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(ROOT)),
  http.get('/api/items/1.1', () => HttpResponse.json(CHILD11)),
  http.get('/api/items/1.1.1', () => HttpResponse.json(ACTION)),
)
beforeAll(() => server.listen())
afterEach(() => { server.resetHandlers(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
  http.get('/api/items/1', () => HttpResponse.json(ROOT)),
  http.get('/api/items/1.1', () => HttpResponse.json(CHILD11)),
  http.get('/api/items/1.1.1', () => HttpResponse.json(ACTION)),
); _resetToken() })
afterAll(() => server.close())

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/items/${path}`]}>
        <Routes>
          <Route path="/items/*" element={<ItemPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemPage', () => {
  it('renders a single-segment breadcrumb for a root', async () => {
    renderAt('1')
    expect(await screen.findByText('root diff')).toBeInTheDocument()
    const crumb = screen.getByTestId('breadcrumb')
    expect(crumb).toHaveTextContent('#1')
    expect(crumb).not.toHaveTextContent('/')
  })

  it('renders a linked multi-segment breadcrumb for an action', async () => {
    renderAt('1.1.1')
    expect(await screen.findByText('ping reviewer')).toBeInTheDocument()
    const crumb = screen.getByTestId('breadcrumb')
    expect(crumb).toHaveTextContent('#1')
    expect(crumb).toHaveTextContent('#1.1')
    expect(crumb).toHaveTextContent('#1.1.1')
    expect(screen.getByRole('link', { name: '#1.1' })).toHaveAttribute('href', '/items/1.1')
  })

  it('lists children collapsed and lazy-loads the next level on expand', async () => {
    renderAt('1')
    expect(await screen.findByText('extracted A')).toBeInTheDocument()
    expect(screen.queryByText('ping reviewer')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('expand-1.1'))
    expect(await screen.findByText('ping reviewer')).toBeInTheDocument()
  })
})
