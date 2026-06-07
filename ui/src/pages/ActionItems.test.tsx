// Action Items page tests (spec Design Section 2.3).
//
// Mirrors Sources.test.tsx: a local render helper with QueryClientProvider +
// MemoryRouter + Toaster, driven through MSW. Covers the five UI states plus the
// three lifecycle mutations (mark-done POST, change-priority POST, snooze POST)
// each hitting MSW and showing a sonner toast.

import {
  describe,
  it,
  expect,
  beforeAll,
  afterAll,
  afterEach,
} from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { ActionItems } from './ActionItems'
import { _resetToken } from '@/lib/api'

const ACTIONS = {
  categories: {
    review: [
      {
        id: 'a1',
        summary: 'Fix bug',
        priority: 'P1',
        parent_item: { id: 'p1', summary: 'Parent thread' },
        action_source: 'triage_response',
        action_category: 'review',
        created_at: '2026-06-01T00:00:00Z',
      },
    ],
  },
  total: 1,
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/actions', () => HttpResponse.json(ACTIONS)),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderActions() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ActionItems />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Action Items page', () => {
  it('renders the loading state while actions are pending', () => {
    server.use(http.get('/api/actions', () => new Promise(() => {})))
    renderActions()
    expect(screen.getByTestId('actions-loading')).toBeInTheDocument()
  })

  it('renders the table from /api/actions', async () => {
    renderActions()
    expect(await screen.findByText('Fix bug')).toBeInTheDocument()
    expect(screen.getByText(/Parent thread/)).toBeInTheDocument()
    // priority is reflected as the selected value of the per-row select
    const prioritySelect = screen.getByRole('combobox', {
      name: /set priority for a1/i,
    }) as HTMLSelectElement
    expect(prioritySelect.value).toBe('P1')
  })

  it('renders the empty state when there are no actions', async () => {
    server.use(
      http.get('/api/actions', () =>
        HttpResponse.json({ categories: {}, total: 0 }),
      ),
    )
    renderActions()
    expect(await screen.findByText(/No action items/i)).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID', async () => {
    server.use(
      http.get('/api/actions', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-a' } },
        ),
      ),
    )
    renderActions()
    await waitFor(() => expect(screen.getByText(/req-a/)).toBeInTheDocument())
  })

  it('renders the unauthorized state when the token endpoint 401s', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
    )
    renderActions()
    await waitFor(() =>
      expect(screen.getByText(/token unavailable/i)).toBeInTheDocument(),
    )
  })

  it('mark done calls POST /done and toasts', async () => {
    let done = false
    server.use(
      ...baseHandlers(),
      http.post('/api/actions/a1/done', () => {
        done = true
        return HttpResponse.json({ status: 'done' })
      }),
    )
    renderActions()
    await userEvent.click(
      await screen.findByRole('button', { name: /mark a1 done/i }),
    )
    await waitFor(() => expect(done).toBe(true))
    expect(await screen.findByText(/marked done/i)).toBeInTheDocument()
  })

  it('change priority calls POST /priority with the chosen value', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers(),
      http.post('/api/actions/a1/priority', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'updated', priority: posted.priority })
      }),
    )
    renderActions()
    const select = await screen.findByRole('combobox', {
      name: /set priority for a1/i,
    })
    await userEvent.selectOptions(select, 'P0')
    await waitFor(() => expect(posted).toMatchObject({ priority: 'P0' }))
  })

  it('snooze calls POST /snooze with hours', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers(),
      http.post('/api/actions/a1/snooze', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'snoozed', hours: posted.hours })
      }),
    )
    renderActions()
    await userEvent.click(
      await screen.findByRole('button', { name: /snooze a1/i }),
    )
    await waitFor(() => expect(posted).toMatchObject({ hours: 4 }))
  })
})
