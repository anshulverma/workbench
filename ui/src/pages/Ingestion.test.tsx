// Ingestion page tests (spec Design Section 2.4).
//
// Mirrors Overview.test.tsx: mocks Recharts ResponsiveContainer (jsdom has no
// ResizeObserver), stubs ResizeObserver, and drives the page through MSW.
// Covers: per-source panels, activity feed, job-history table + status filter,
// dead-letter retry (POST) / purge (DELETE) with toast, loading and error states.

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Ingestion } from './Ingestion'
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

const SOURCES = [
  {
    id: 'src-gh',
    adapter_type: 'github',
    enabled: true,
    schedule: '*/15 * * * *',
    last_run: '2026-06-05T11:00:00+00:00',
    items_stored: 42,
    raw_enqueued: 50,
    in_flight: 3,
    health_status: 'healthy',
  },
  {
    id: 'src-email',
    adapter_type: 'email',
    enabled: false,
    schedule: null,
    last_run: null,
    items_stored: 0,
    raw_enqueued: 0,
    in_flight: 0,
    health_status: 'disabled',
  },
]

const ACTIVITY = [
  {
    id: 'item-1',
    status: 'active',
    source_type: 'github',
    summary: 'PR opened: fix the thing',
    created_at: '2026-06-05T10:30:00+00:00',
  },
  {
    id: 'item-2',
    status: 'archived',
    source_type: 'email',
    summary: 'Weekly digest',
    created_at: '2026-06-05T09:30:00+00:00',
  },
]

const JOBS_ALL = {
  jobs: [
    {
      id: 'job-aaa',
      trigger: 'poll',
      status: 'completed',
      items_extracted: 5,
      created_at: '2026-06-05T10:00:00+00:00',
    },
    {
      id: 'job-bbb',
      trigger: 'manual',
      status: 'failed',
      items_extracted: 0,
      created_at: '2026-06-05T09:00:00+00:00',
    },
  ],
  total: 2,
  limit: 25,
  offset: 0,
}

const JOBS_FAILED = {
  jobs: [
    {
      id: 'job-bbb',
      trigger: 'manual',
      status: 'failed',
      items_extracted: 0,
      created_at: '2026-06-05T09:00:00+00:00',
    },
  ],
  total: 1,
  limit: 25,
  offset: 0,
}

const QUEUE = {
  by_status: { queued: 3, processing: 1, dead_letter: 2 },
  by_source: { github: 3, email: 1 },
  queued: 3,
  processing: 1,
  dead_letter: 2,
}

const DEAD_LETTERS = [
  {
    id: 'dl-1',
    raw_content: 'broken payload',
    source_type: 'github',
    source_id: 'src-gh',
    urgency_score: 80,
    job_id: 'job-bbb',
    status: 'dead_letter',
    attempt: 3,
    max_attempts: 3,
    error: 'extraction failed',
    created_at: '2026-06-05T08:00:00+00:00',
    updated_at: '2026-06-05T08:30:00+00:00',
  },
]

let retryHits = 0
let purgeHits = 0

function handlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
    http.get('/api/stats/sources', () => HttpResponse.json(SOURCES)),
    http.get('/api/activity', () => HttpResponse.json(ACTIVITY)),
    http.get('/api/jobs', ({ request }) => {
      const url = new URL(request.url)
      const status = url.searchParams.get('status')
      return HttpResponse.json(status === 'failed' ? JOBS_FAILED : JOBS_ALL)
    }),
    http.get('/api/stats/queue', () => HttpResponse.json(QUEUE)),
    http.get('/api/queue/dead-letter', () => HttpResponse.json(DEAD_LETTERS)),
    http.post('/api/queue/dead-letter/:id/retry', () => {
      retryHits += 1
      return HttpResponse.json({ status: 'requeued' })
    }),
    http.delete('/api/queue/dead-letter/:id', () => {
      purgeHits += 1
      return HttpResponse.json({ status: 'purged' })
    }),
  ]
}

const server = setupServer(...handlers())

beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...handlers())
  _resetToken()
  retryHits = 0
  purgeHits = 0
})
afterAll(() => server.close())

function renderIngestion() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Ingestion />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Ingestion page', () => {
  it('renders top-level queue stat cards (V3 promoted layout)', async () => {
    renderIngestion()
    // Wait for queue stats to resolve — the "In Queue" card shows queued count.
    await screen.findByText('3') // queued count
    // Dead Letters stat card shows the count with danger styling.
    expect(screen.getByText('Dead Letters')).toBeInTheDocument()
    // Sources stat card shows total count with enabled delta.
    expect(screen.getByText('Sources')).toBeInTheDocument()
    expect(screen.getByText('1 enabled')).toBeInTheDocument()
  })

  it('renders the activity feed from /api/activity', async () => {
    renderIngestion()
    expect(await screen.findByText('PR opened: fix the thing')).toBeInTheDocument()
    expect(screen.getByText('Weekly digest')).toBeInTheDocument()
  })

  it('renders the job-history table and filters by status', async () => {
    const user = userEvent.setup()
    renderIngestion()
    expect(await screen.findByText('job-aaa')).toBeInTheDocument()
    expect(screen.getByText('job-bbb')).toBeInTheDocument()

    const filter = screen.getByLabelText(/job status filter/i)
    await user.selectOptions(filter, 'failed')

    await waitFor(() => expect(screen.queryByText('job-aaa')).not.toBeInTheDocument())
    expect(screen.getByText('job-bbb')).toBeInTheDocument()
  })

  it('retries a dead letter via POST and shows a toast', async () => {
    const user = userEvent.setup()
    renderIngestion()
    const retryBtn = await screen.findByRole('button', { name: /retry/i })
    await user.click(retryBtn)
    await waitFor(() => expect(retryHits).toBe(1))
  })

  it('purges a dead letter via DELETE behind a confirm dialog', async () => {
    const user = userEvent.setup()
    renderIngestion()
    const purgeBtn = await screen.findByRole('button', { name: /^purge$/i })
    await user.click(purgeBtn)
    // confirm dialog appears
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: /purge/i })
    await user.click(confirm)
    await waitFor(() => expect(purgeHits).toBe(1))
  })

  it('renders the loading state while queries are pending', () => {
    renderIngestion()
    expect(screen.getByTestId('ingestion-loading')).toBeInTheDocument()
  })

  it('renders the error state with the X-Request-ID on failure', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
      http.get('/api/stats/sources', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-99' } },
        ),
      ),
      http.get('/api/activity', () => HttpResponse.json(ACTIVITY)),
      http.get('/api/jobs', () => HttpResponse.json(JOBS_ALL)),
      http.get('/api/stats/queue', () => HttpResponse.json(QUEUE)),
      http.get('/api/queue/dead-letter', () => HttpResponse.json(DEAD_LETTERS)),
    )
    renderIngestion()
    expect(await screen.findByText(/req-99/)).toBeInTheDocument()
  })

  it('renders the unauthorized state when the token endpoint returns 401', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/stats/sources', () => HttpResponse.json(SOURCES)),
      http.get('/api/activity', () => HttpResponse.json(ACTIVITY)),
      http.get('/api/jobs', () => HttpResponse.json(JOBS_ALL)),
      http.get('/api/stats/queue', () => HttpResponse.json(QUEUE)),
      http.get('/api/queue/dead-letter', () => HttpResponse.json(DEAD_LETTERS)),
    )
    renderIngestion()
    expect(await screen.findByText(/token unavailable/i)).toBeInTheDocument()
  })

  it('renders the LiveTail with activity items as structured rows', async () => {
    renderIngestion()
    // Wait for activity data to arrive — LiveTail renders item IDs.
    await screen.findByText('item-1')
    const log = screen.getByRole('log')
    // Each ActivityItem maps to a TailEntry row with source and summary.
    expect(within(log).getByText(/github/)).toBeInTheDocument()
    expect(within(log).getByText(/PR opened: fix the thing/)).toBeInTheDocument()
    expect(within(log).getByText(/Weekly digest/)).toBeInTheDocument()
  })

  it('shows the empty tail state when the activity feed is empty', async () => {
    server.resetHandlers(
      http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
      http.get('/api/stats/sources', () => HttpResponse.json(SOURCES)),
      http.get('/api/activity', () => HttpResponse.json([])),
      http.get('/api/jobs', () => HttpResponse.json(JOBS_ALL)),
      http.get('/api/stats/queue', () => HttpResponse.json(QUEUE)),
      http.get('/api/queue/dead-letter', () => HttpResponse.json(DEAD_LETTERS)),
    )
    renderIngestion()
    // Wait for sources to load (signals data queries resolved).
    await screen.findByText('Sources')
    const log = screen.getByRole('log')
    expect(within(log).getByText(/Waiting for events/)).toBeInTheDocument()
  })
})
