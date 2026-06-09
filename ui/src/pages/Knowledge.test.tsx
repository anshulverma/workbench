// Knowledge page tests (spec Design Section 2.7, plan Task E5).
//
// Local render helper with QueryClientProvider + MemoryRouter + Toaster, driven
// through MSW (mirrors Messenger.test.tsx). Covers: facts list rendering from a
// mocked envelope, client-side search filtering, group-by-source grouping, the
// THREE distinct empty/degraded states, delete behind a confirm dialog (DELETE
// MSW hit), edit (PATCH MSW hit), a 501 curation call surfacing the friendly
// toast, and the loading / error / unauthorized states.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Knowledge } from './Knowledge'
import { _resetToken } from '@/lib/api'

const FACTS = [
  {
    id: 'f1',
    content: 'prioritizes blocked PRs',
    source: 'interaction',
    timestamp: '2026-06-01T00:00:00Z',
  },
  {
    id: 'f2',
    content: 'ignores marketing newsletters',
    source: 'feedback',
    timestamp: '2026-06-02T00:00:00Z',
  },
]

function statsOverview(overrides: Record<string, unknown> = {}) {
  return {
    pending_triage: 0,
    in_flight: 0,
    dead_letters: 0,
    active_items: 0,
    sources_enabled: 3,
    sources_total: 5,
    items: {
      by_status: {},
      by_priority: {},
      by_category: {},
      by_source: {},
      total: 0,
    },
    queue: { in_flight: 0, dead_letters: 0 },
    metrics: {
      signal_velocity: 0,
      throughput: 0,
      efficiency_peak: null,
      auto_resolved_pct: null,
      avg_triage_seconds: null,
      growth_velocity: null,
      ingestion_success_rate: null,
    },
    ...overrides,
  }
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/stats/overview', () => HttpResponse.json(statsOverview())),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Knowledge />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Knowledge page', () => {
  it('renders the loading state while the query is pending', () => {
    server.use(http.get('/api/memory/facts', () => new Promise(() => {})))
    renderPage()
    expect(screen.getByTestId('knowledge-loading')).toBeInTheDocument()
  })

  it('renders the facts list from the envelope', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    expect(await screen.findByText('prioritizes blocked PRs')).toBeInTheDocument()
    expect(screen.getByText('ignores marketing newsletters')).toBeInTheDocument()
  })

  it('search filters the facts list', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    await screen.findByText('prioritizes blocked PRs')
    await userEvent.type(screen.getByLabelText('Search facts'), 'marketing')
    await waitFor(() =>
      expect(screen.queryByText('prioritizes blocked PRs')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('ignores marketing newsletters')).toBeInTheDocument()
  })

  it('group-by-source groups facts under their source', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    await screen.findByText('prioritizes blocked PRs')
    await userEvent.click(screen.getByLabelText('Group by source'))
    const interaction = await screen.findByRole('region', { name: 'Source interaction' })
    const feedback = screen.getByRole('region', { name: 'Source feedback' })
    expect(within(interaction).getByText('prioritizes blocked PRs')).toBeInTheDocument()
    expect(within(feedback).getByText('ignores marketing newsletters')).toBeInTheDocument()
  })

  it('degraded: noop memory layer not enabled', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: false, memory_type: 'noop', facts: [] }),
      ),
    )
    renderPage()
    expect(await screen.findByText(/Memory layer not enabled/i)).toBeInTheDocument()
  })

  it('degraded: configured but unreachable shows the request id', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json(
          { available: false, memory_type: 'zep', facts: [] },
          { headers: { 'X-Request-ID': 'req-mem' } },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText(/Memory service unreachable/i)).toBeInTheDocument()
    expect(screen.getByText(/req-mem/)).toBeInTheDocument()
  })

  it('empty: configured with no facts', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: [] }),
      ),
    )
    renderPage()
    expect(await screen.findByText(/No preference facts learned yet/i)).toBeInTheDocument()
  })

  it('delete calls DELETE behind a confirm dialog', async () => {
    let deleted = false
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
      http.delete('/api/memory/facts/f1', () => {
        deleted = true
        return HttpResponse.json({ status: 'deleted' })
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /delete f1/i }))
    await userEvent.click(await screen.findByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(deleted).toBe(true))
    expect(await screen.findByText(/fact deleted/i)).toBeInTheDocument()
  })

  it('edit calls PATCH with the new content', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
      http.patch('/api/memory/facts/f1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'updated' })
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /edit f1/i }))
    const textarea = await screen.findByLabelText('Content for f1')
    await userEvent.clear(textarea)
    await userEvent.type(textarea, 'updated fact text')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() =>
      expect(patched).toMatchObject({ content: 'updated fact text' }),
    )
    expect(await screen.findByText(/fact updated/i)).toBeInTheDocument()
  })

  it('a 501 delete surfaces the friendly "not configured" toast', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
      http.delete('/api/memory/facts/f1', () =>
        HttpResponse.json({ detail: 'memory layer not configured' }, { status: 501 }),
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /delete f1/i }))
    await userEvent.click(await screen.findByRole('button', { name: /confirm/i }))
    expect(
      await screen.findByText(/memory layer not configured/i),
    ).toBeInTheDocument()
  })

  it('does not render fact content as HTML', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({
          available: true,
          memory_type: 'zep',
          facts: [
            {
              id: 'fx',
              content: '<img src=x onerror=alert(1)>',
              source: 'interaction',
              timestamp: null,
            },
          ],
        }),
      ),
    )
    const { container } = renderPage()
    // The raw string is shown as text; no <img> element is injected.
    expect(
      await screen.findByText('<img src=x onerror=alert(1)>'),
    ).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders the error state with the X-Request-ID on failure', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-5' } },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText(/req-5/)).toBeInTheDocument()
  })

  it('renders stat cards: total facts, active sources, and growth velocity n/a', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    const total = await screen.findByTestId('stat-total-facts')
    expect(within(total).getByText('2')).toBeInTheDocument()
    const sources = screen.getByTestId('stat-active-sources')
    expect(within(sources).getByText('3')).toBeInTheDocument()
    // growth_velocity is null in the overview -> "n/a", never fabricated.
    const growth = screen.getByTestId('stat-growth-velocity')
    expect(within(growth).getByText('n/a')).toBeInTheDocument()
  })

  it('renders growth velocity scalar when present', async () => {
    server.use(
      http.get('/api/stats/overview', () =>
        HttpResponse.json(statsOverview({ metrics: { ...statsOverview().metrics, growth_velocity: 4.5 } })),
      ),
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    const growth = await screen.findByTestId('stat-growth-velocity')
    expect(within(growth).getByText('4.5')).toBeInTheDocument()
  })

  it('renders the facts table with source pills and created dates', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({
          available: true,
          memory_type: 'zep',
          facts: [
            { id: 'f1', content: 'has a timestamp', source: 'interaction', timestamp: '2026-06-01T00:00:00Z' },
            { id: 'f2', content: 'no timestamp', source: '', timestamp: null },
          ],
        }),
      ),
    )
    renderPage()
    const row1 = (await screen.findByText('has a timestamp')).closest('tr')!
    expect(within(row1).getByText('interaction')).toBeInTheDocument()
    // Empty source renders the "unknown" pill.
    const row2 = screen.getByText('no timestamp').closest('tr')!
    expect(within(row2).getByText('unknown')).toBeInTheDocument()
    // Null timestamp renders an em-dash.
    expect(within(row2).getByText('—')).toBeInTheDocument()
  })

  it('Add Fact POSTs the content and shows the manual fact', async () => {
    let posted: Record<string, unknown> | null = null
    const facts = [...FACTS]
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts }),
      ),
      http.post('/api/memory/facts', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        const created = {
          id: 'f3',
          content: String(posted.content),
          source: 'manual',
          timestamp: '2026-06-08T00:00:00Z',
        }
        facts.push(created)
        return HttpResponse.json(created)
      }),
    )
    renderPage()
    await screen.findByText('prioritizes blocked PRs')
    await userEvent.click(screen.getByRole('button', { name: /add fact/i }))
    const textarea = await screen.findByLabelText('New fact content')
    await userEvent.type(textarea, 'manually added fact')
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }))
    await waitFor(() => expect(posted).toMatchObject({ content: 'manually added fact' }))
    const row = (await screen.findByText('manually added fact')).closest('tr')!
    expect(within(row).getByText('manual')).toBeInTheDocument()
  })

  it('Add Fact 422 on blank content shows an inline error', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
      http.post('/api/memory/facts', () =>
        HttpResponse.json({ detail: 'content must not be empty' }, { status: 422 }),
      ),
    )
    renderPage()
    await screen.findByText('prioritizes blocked PRs')
    await userEvent.click(screen.getByRole('button', { name: /add fact/i }))
    const textarea = await screen.findByLabelText('New fact content')
    await userEvent.type(textarea, '   ')
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }))
    expect(await screen.findByText(/content must not be empty/i)).toBeInTheDocument()
    // The dialog stays open after a 422 so the user can correct the input.
    expect(screen.getByLabelText('New fact content')).toBeInTheDocument()
  })

  it('Add Fact is hidden when the memory layer is unreachable', async () => {
    server.use(
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: false, memory_type: 'zep', facts: [] }),
      ),
    )
    renderPage()
    await screen.findByText(/Memory service unreachable/i)
    expect(screen.queryByRole('button', { name: /add fact/i })).not.toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/memory/facts', () =>
        HttpResponse.json({ available: true, memory_type: 'zep', facts: FACTS }),
      ),
    )
    renderPage()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })
})
