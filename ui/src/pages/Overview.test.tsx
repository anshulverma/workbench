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
  metrics: {
    signal_velocity: 18,
    throughput: 9,
    efficiency_peak: 0.8,
    auto_resolved_pct: 0.84,
    avg_triage_seconds: 720,
    growth_velocity: null,
    ingestion_success_rate: 0.97,
  },
}

const TIMESERIES = [
  { date: '2026-05-23T00:00:00+00:00', count: 3 },
  { date: '2026-05-24T00:00:00+00:00', count: 5 },
  { date: '2026-05-25T00:00:00+00:00', count: 2 },
]

// /api/stats/timeseries (signal velocity sparkline) — {bucket, count}.
const METRIC_TIMESERIES = [
  { bucket: '2026-06-08T08:00:00+00:00', count: 2 },
  { bucket: '2026-06-08T09:00:00+00:00', count: 5 },
  { bucket: '2026-06-08T10:00:00+00:00', count: 3 },
]

// /api/topology — node-link graph composed from live health probes.
const TOPOLOGY = {
  nodes: [
    { id: 'app', label: 'Workbench', kind: 'app', status: 'healthy' },
    { id: 'storage', label: 'PostgreSQL', kind: 'storage', status: 'healthy' },
    {
      id: 'memory',
      label: 'Memory Service',
      kind: 'memory_service',
      status: 'not_configured',
    },
    { id: 'github', label: 'github', kind: 'adapter', status: 'degraded' },
  ],
  edges: [
    { from: 'app', to: 'storage', kind: 'connection' },
    { from: 'app', to: 'memory', kind: 'connection' },
    { from: 'app', to: 'github', kind: 'adapter' },
  ],
}

// /api/items?status=pending_triage — HOT FEED source (filtered to P0/P1).
const ITEMS = [
  {
    id: 'item-p0',
    source_type: 'github',
    source_id: 'gh-1',
    summary: 'Production DB latency spike: US-EAST-1',
    category: 'action_item',
    origin: 'ingested',
    priority: 'P0',
    status: 'pending_triage',
    created_at: '2026-06-08T09:30:00+00:00',
    updated_at: '2026-06-08T09:30:00+00:00',
  },
  {
    id: 'item-p1',
    source_type: 'email',
    source_id: 'em-1',
    summary: 'PR #842 OAuth refactor needs review',
    category: 'action_item',
    origin: 'ingested',
    priority: 'P1',
    status: 'pending_triage',
    created_at: '2026-06-08T08:00:00+00:00',
    updated_at: '2026-06-08T08:00:00+00:00',
  },
  {
    id: 'item-p2',
    source_type: 'slack',
    source_id: 'sl-1',
    summary: 'Weekly cost summary (should be filtered out of hot feed)',
    category: 'informational',
    origin: 'ingested',
    priority: 'P2',
    status: 'pending_triage',
    created_at: '2026-06-08T07:00:00+00:00',
    updated_at: '2026-06-08T07:00:00+00:00',
  },
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

function handlers(
  overrides: { overview?: object; deadLetters?: number } = {},
) {
  const overview = overrides.deadLetters
    ? { ...OVERVIEW, dead_letters: overrides.deadLetters, queue: { ...OVERVIEW.queue, dead_letters: overrides.deadLetters } }
    : overrides.overview ?? OVERVIEW
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
    http.get('/api/stats/overview', () => HttpResponse.json(overview)),
    http.get('/api/stats/ingestion-timeseries', () => HttpResponse.json(TIMESERIES)),
    http.get('/api/stats/timeseries', () => HttpResponse.json(METRIC_TIMESERIES)),
    http.get('/api/topology', () => HttpResponse.json(TOPOLOGY)),
    http.get('/api/stats/sources', () => HttpResponse.json([])),
    http.get('/api/items', () => HttpResponse.json(ITEMS)),
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

    // values — scoped to the stat-card grid (the hero header also shows some
    // of these counts, so query within the grid to stay unambiguous).
    const grid = await screen.findByTestId('stat-grid')
    const within = (re: RegExp | string) =>
      Array.from(grid.querySelectorAll('*')).some((el) =>
        el.childElementCount === 0 &&
        (typeof re === 'string' ? el.textContent === re : re.test(el.textContent ?? '')),
      )
    await waitFor(() => expect(within('4')).toBe(true)) // pending
    expect(within('7')).toBe(true) // in_flight
    expect(within('12')).toBe(true) // active items
    expect(within('2 / 3')).toBe(true) // sources enabled/total
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
      http.get('/api/stats/timeseries', () => HttpResponse.json(METRIC_TIMESERIES)),
      http.get('/api/topology', () => HttpResponse.json(TOPOLOGY)),
      http.get('/api/stats/sources', () => HttpResponse.json([])),
      http.get('/api/items', () => HttpResponse.json(ITEMS)),
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
      http.get('/api/stats/timeseries', () => HttpResponse.json(METRIC_TIMESERIES)),
      http.get('/api/topology', () => HttpResponse.json(TOPOLOGY)),
      http.get('/api/stats/sources', () => HttpResponse.json([])),
      http.get('/api/items', () => HttpResponse.json(ITEMS)),
      http.get('/api/jobs', () => HttpResponse.json(JOBS)),
      http.get('/health', () => HttpResponse.json(HEALTH)),
      http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    )
    renderOverview()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })

  // --- Hero region (P1, spec §8) ---

  it('renders the attention header from real metrics (P0 active + pending)', async () => {
    renderOverview()
    const header = await screen.findByTestId('attention-header')
    // P0 active items (by_priority.P0 = 1) and pending triage (4).
    expect(header).toHaveTextContent(/P0/i)
    expect(header).toHaveTextContent(/1/)
    expect(header).toHaveTextContent(/pending/i)
    expect(header).toHaveTextContent(/4/)
  })

  it('does NOT render hollow widgets (active sessions / unread pings / blocked tasks)', async () => {
    renderOverview()
    await screen.findByTestId('attention-header')
    expect(screen.queryByText(/unread pings/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/blocked tasks/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/active sessions/i)).not.toBeInTheDocument()
  })

  it('renders the HOT FEED with only P0/P1 pending items (drops P2)', async () => {
    renderOverview()
    const feed = await screen.findByTestId('hot-feed')
    // wait for the async items query to settle before asserting content
    await waitFor(() =>
      expect(feed).toHaveTextContent(/Production DB latency spike/i),
    )
    expect(feed).toHaveTextContent(/OAuth refactor/i)
    expect(feed).not.toHaveTextContent(/Weekly cost summary/i)
  })

  it('renders the INITIATE TRIAGE CTA linking to /triage with the pending count', async () => {
    renderOverview()
    const cta = await screen.findByTestId('initiate-triage')
    expect(cta).toHaveAttribute('href', '/triage')
    expect(cta).toHaveTextContent(/4/)
  })

  it('renders the ingestion-success-rate tile as a percentage', async () => {
    renderOverview()
    const tile = await screen.findByTestId('ingestion-success-tile')
    expect(tile).toHaveTextContent(/97%/)
  })

  it('renders "n/a" for the ingestion-success-rate tile when the metric is null', async () => {
    server.resetHandlers(
      ...handlers({
        overview: {
          ...OVERVIEW,
          metrics: { ...OVERVIEW.metrics, ingestion_success_rate: null },
        },
      }),
    )
    renderOverview()
    const tile = await screen.findByTestId('ingestion-success-tile')
    expect(tile).toHaveTextContent(/n\/a/i)
  })

  it('renders the topology panel with an SVG (role=img) and a visually-hidden table fallback', async () => {
    renderOverview()
    const panel = await screen.findByTestId('topology-panel')
    // wait for the async topology query to settle before asserting the SVG
    await waitFor(() =>
      expect(panel.querySelector('svg[role="img"]')).toBeTruthy(),
    )
    // a11y table fallback lists nodes + statuses
    const table = panel.querySelector('table')
    expect(table).toBeTruthy()
    expect(table).toHaveTextContent(/Workbench/)
    expect(table).toHaveTextContent(/PostgreSQL/)
    expect(table).toHaveTextContent(/not_configured/)
  })

  it('keeps all existing widgets present alongside the hero region', async () => {
    renderOverview()
    // existing stat cards + charts + jobs still render
    expect(await screen.findByText('Pending Triage')).toBeInTheDocument()
    expect(screen.getByText('Items by Priority')).toBeInTheDocument()
    expect(screen.getByText('Recent Jobs')).toBeInTheDocument()
    // hero coexists
    expect(screen.getByTestId('hot-feed')).toBeInTheDocument()
  })
})
