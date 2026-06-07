// Overview page tests (spec Design Section 2.1).
//
// Recharts renders inside a ResponsiveContainer that measures its parent via
// ResizeObserver, which jsdom does not implement (it reports 0x0 and the chart
// never paints). We mock ResponsiveContainer to a fixed-size <div> so the chart
// SVG renders deterministically. We also stub ResizeObserver defensively.

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Overview } from './Overview'
import { _resetToken } from '@/lib/api'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={{ width: 600, height: 300 }} data-testid="responsive-container">
        {children}
      </div>
    ),
  }
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub

const OVERVIEW = {
  pending_triage: 4,
  in_flight: 7,
  dead_letters: 0,
  active_items: 12,
  sources_enabled: 2,
  sources_total: 3,
  items: {
    by_status: { active: 12, archived: 3 },
    by_priority: { P0: 1, P1: 4, P2: 5, P3: 2 },
    by_category: {
      action_item: 6,
      meeting: 2,
      plan_seed: 1,
      informational: 3,
    },
    by_source: { github: 8, email: 4 },
    total: 15,
  },
  queue: { in_flight: 7, dead_letters: 0 },
}

const TIMESERIES = [
  { date: '2026-05-23T00:00:00+00:00', count: 3 },
  { date: '2026-05-24T00:00:00+00:00', count: 5 },
  { date: '2026-05-25T00:00:00+00:00', count: 2 },
]

const JOBS = {
  jobs: [
    {
      id: 'job-abc123',
      trigger: 'poll',
      status: 'completed',
      items_extracted: 5,
      created_at: '2026-06-05T10:00:00+00:00',
    },
    {
      id: 'job-def456',
      trigger: 'manual',
      status: 'failed',
      items_extracted: 0,
      created_at: '2026-06-05T09:00:00+00:00',
    },
  ],
  total: 2,
  limit: 10,
  offset: 0,
}

const HEALTH = {
  status: 'healthy',
  version: '0.1.0',
  components: { storage: { status: 'healthy' }, connections: {} },
  queue: { ingestion_depth: 7, triage_pending: 4, dead_letters: 0 },
}

const MESSENGER = {
  configured: true,
  type: 'google_chat',
  class: 'GoogleChatMessenger',
  config: { space_id: 'spaces/AAA' },
}

function handlers(overrides: { overview?: object; deadLetters?: number } = {}) {
  const overview = overrides.deadLetters
    ? { ...OVERVIEW, dead_letters: overrides.deadLetters, queue: { ...OVERVIEW.queue, dead_letters: overrides.deadLetters } }
    : overrides.overview ?? OVERVIEW
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
    http.get('/api/stats/overview', () => HttpResponse.json(overview)),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json(TIMESERIES)),
    http.get('/api/jobs', () => HttpResponse.json(JOBS)),
    http.get('/health', () => HttpResponse.json(HEALTH)),
    http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
  ]
}

const server = setupServer(...handlers())

beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...handlers())
  _resetToken()
})
afterAll(() => server.close())

function renderOverview() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Overview />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Overview page', () => {
  it('renders all six stat cards from the mocked endpoints', async () => {
    renderOverview()
    expect(await screen.findByText('Pending Triage')).toBeInTheDocument()
    expect(screen.getByText('Ingestion Queue')).toBeInTheDocument()
    expect(screen.getByText('Dead Letters')).toBeInTheDocument()
    expect(screen.getByText('Active Items')).toBeInTheDocument()
    expect(screen.getByText('Sources')).toBeInTheDocument()
    expect(screen.getByText('Messenger')).toBeInTheDocument()

    // values
    await waitFor(() => expect(screen.getByText('4')).toBeInTheDocument()) // pending
    expect(screen.getByText('7')).toBeInTheDocument() // in_flight
    expect(screen.getByText('12')).toBeInTheDocument() // active items
    expect(screen.getByText('2 / 3')).toBeInTheDocument() // sources enabled/total
  })

  it('renders the four chart cards by title', async () => {
    renderOverview()
    expect(await screen.findByText('Ingestion (14 days)')).toBeInTheDocument()
    expect(screen.getByText('Items by Priority')).toBeInTheDocument()
    expect(screen.getByText('Items by Source')).toBeInTheDocument()
    expect(screen.getByText('Items by Category')).toBeInTheDocument()
  })

  it('renders the recent jobs table', async () => {
    renderOverview()
    expect(await screen.findByText('Recent Jobs')).toBeInTheDocument()
    expect(await screen.findByText('job-abc123')).toBeInTheDocument()
    expect(screen.getByText('job-def456')).toBeInTheDocument()
  })

  it('does NOT show the dead-letter banner when dead_letters is 0', async () => {
    renderOverview()
    await screen.findByText('Pending Triage')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the dead-letter banner only when dead_letters > 0', async () => {
    server.resetHandlers(...handlers({ deadLetters: 3 }))
    renderOverview()
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/3/)
  })

  it('renders the loading state while queries are pending', () => {
    renderOverview()
    expect(screen.getByTestId('overview-loading')).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID on failure', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
      http.get('/api/stats/overview', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-42' } },
        ),
      ),
      http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json(TIMESERIES)),
      http.get('/api/jobs', () => HttpResponse.json(JOBS)),
      http.get('/health', () => HttpResponse.json(HEALTH)),
      http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    )
    renderOverview()
    expect(await screen.findByText(/req-42/)).toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/stats/overview', () => HttpResponse.json(OVERVIEW)),
      http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json(TIMESERIES)),
      http.get('/api/jobs', () => HttpResponse.json(JOBS)),
      http.get('/health', () => HttpResponse.json(HEALTH)),
      http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    )
    renderOverview()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })
})
