// Overview page tests (spec Design Section 2.1).
//
// The Overview page mirrors the design prototype: a compact clickable status
// strip, the Signal Flow Sankey hero, and a full-width Hot Feed. The legacy
// topology / charts / recent-jobs / stat-grid sections were removed. Five UI
// states are preserved (loading / error / empty / unauthorized / degraded).
//
// Recharts (used by SourceFlow) renders inside a ResponsiveContainer that
// measures its parent via ResizeObserver, which jsdom does not implement. We
// mock ResponsiveContainer to a fixed-size <div> and stub ResizeObserver.

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

// /api/stats/sources — per-source rollup feeding the Signal Flow Sankey.
const SOURCES_ROLLUP = [
  {
    id: 'src-gh',
    adapter_type: 'github',
    enabled: true,
    schedule: '*/15 * * * *',
    last_run: '2026-06-08T11:00:00+00:00',
    items_stored: 42,
    raw_enqueued: 50,
    in_flight: 3,
    health_status: 'healthy',
  },
  {
    id: 'src-email',
    adapter_type: 'email',
    enabled: true,
    schedule: '0 * * * *',
    last_run: '2026-06-08T10:00:00+00:00',
    items_stored: 12,
    raw_enqueued: 14,
    in_flight: 1,
    health_status: 'healthy',
  },
]

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
  overrides: { overview?: object; deadLetters?: number; messenger?: object } = {},
) {
  const overview = overrides.deadLetters
    ? { ...OVERVIEW, dead_letters: overrides.deadLetters, queue: { ...OVERVIEW.queue, dead_letters: overrides.deadLetters } }
    : overrides.overview ?? OVERVIEW
  const messenger = overrides.messenger ?? MESSENGER
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
    http.get('/api/stats/overview', () => HttpResponse.json(overview)),
    http.get('/api/stats/sources', () => HttpResponse.json(SOURCES_ROLLUP)),
    http.get('/api/items', () => HttpResponse.json(ITEMS)),
    http.get('/health', () => HttpResponse.json(HEALTH)),
    http.get('/api/messenger', () => HttpResponse.json(messenger)),
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
  // --- Status strip ---

  it('renders the status strip with its navigable tiles', async () => {
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    expect(strip).toBeInTheDocument()
    // Tiles present in the strip.
    expect(within(strip).getByText('Ingestion Queue')).toBeInTheDocument()
    expect(within(strip).getByText('Ingest Rate')).toBeInTheDocument()
    expect(within(strip).getByText('Active Items')).toBeInTheDocument()
    expect(within(strip).getByText('Sources')).toBeInTheDocument()
    expect(within(strip).getByText('Messenger')).toBeInTheDocument()
    // Sources tile shows enabled/total.
    expect(within(strip).getByText('2/3')).toBeInTheDocument()
    // Ingest Rate tile renders the success rate as a percent.
    expect(within(strip).getByText('97%')).toBeInTheDocument()
  })

  it('renders the Initiate Triage primary tile with pending + P0 counts', async () => {
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    const tile = within(strip).getByText(/Initiate Triage/i).closest('button')!
    expect(tile).toBeInTheDocument()
    // pending_triage = 4, by_priority.P0 = 1
    expect(tile).toHaveTextContent(/4/)
    expect(tile).toHaveTextContent(/pending/i)
    expect(tile).toHaveTextContent(/1 P0 active/i)
  })

  it('renders "GChat" in the Messenger tile when configured', async () => {
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    expect(within(strip).getByText('GChat')).toBeInTheDocument()
  })

  it('renders "Unset" in the Messenger tile when not configured', async () => {
    server.resetHandlers(...handlers({ messenger: { configured: false } }))
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    expect(within(strip).getByText('Unset')).toBeInTheDocument()
  })

  it('omits the Dead Letters tile when dead_letters is 0', async () => {
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    expect(within(strip).queryByText('Dead Letters')).not.toBeInTheDocument()
  })

  it('shows the Dead Letters tile only when dead_letters > 0', async () => {
    server.resetHandlers(...handlers({ deadLetters: 3 }))
    renderOverview()
    const strip = await screen.findByTestId('status-strip')
    const tile = within(strip).getByText('Dead Letters').closest('button')!
    expect(tile).toHaveTextContent(/3/)
  })

  // --- Signal Flow card ---

  it('renders the Signal Flow card', async () => {
    renderOverview()
    const card = await screen.findByTestId('signal-flow-card')
    expect(card).toBeInTheDocument()
    expect(within(card).getByText('Signal Flow')).toBeInTheDocument()
  })

  // --- Degraded banner ---

  it('does NOT show the degraded banner when the messenger is configured', async () => {
    renderOverview()
    await screen.findByTestId('status-strip')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows the degraded banner when the messenger is not configured', async () => {
    server.resetHandlers(...handlers({ messenger: { configured: false } }))
    renderOverview()
    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent(/Messenger not configured/i)
  })

  // --- Hot Feed ---

  it('renders the HOT FEED with only P0/P1 pending items (drops P2)', async () => {
    renderOverview()
    const feed = await screen.findByTestId('hot-feed')
    await waitFor(() =>
      expect(feed).toHaveTextContent(/Production DB latency spike/i),
    )
    expect(feed).toHaveTextContent(/OAuth refactor/i)
    expect(feed).not.toHaveTextContent(/Weekly cost summary/i)
  })

  it('opens the item funnel dialog when a hot feed item is clicked', async () => {
    const user = userEvent.setup()
    renderOverview()
    await screen.findByTestId('hot-feed')
    const row = await screen.findByTestId('hot-feed-item-item-p0')
    await user.click(row)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/Production DB latency spike/i)
  })

  // --- UI states ---

  it('renders the loading state while queries are pending', () => {
    renderOverview()
    expect(screen.getByTestId('overview-loading')).toBeInTheDocument()
  })

  it('renders the error state on failure', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
      http.get('/api/stats/overview', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-42' } },
        ),
      ),
      http.get('/api/stats/sources', () => HttpResponse.json(SOURCES_ROLLUP)),
      http.get('/api/items', () => HttpResponse.json(ITEMS)),
      http.get('/health', () => HttpResponse.json(HEALTH)),
      http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    )
    renderOverview()
    expect(await screen.findByText(/Failed to load overview/i)).toBeInTheDocument()
  })

  it('renders the empty state when there is no activity', async () => {
    const EMPTY = {
      ...OVERVIEW,
      pending_triage: 0,
      in_flight: 0,
      dead_letters: 0,
      active_items: 0,
      sources_enabled: 0,
      sources_total: 0,
      items: { ...OVERVIEW.items, total: 0 },
      queue: { in_flight: 0, dead_letters: 0 },
    }
    server.resetHandlers(...handlers({ overview: EMPTY }))
    renderOverview()
    expect(await screen.findByText(/No activity yet/i)).toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/stats/overview', () => HttpResponse.json(OVERVIEW)),
      http.get('/api/stats/sources', () => HttpResponse.json(SOURCES_ROLLUP)),
      http.get('/api/items', () => HttpResponse.json(ITEMS)),
      http.get('/health', () => HttpResponse.json(HEALTH)),
      http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    )
    renderOverview()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })
})
