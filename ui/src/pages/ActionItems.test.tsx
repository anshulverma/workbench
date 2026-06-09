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
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { ActionItems } from './ActionItems'
import { _resetToken } from '@/lib/api'

const HOUR = 3600_000
const now = Date.now()
const iso = (msAgo: number) => new Date(now - msAgo).toISOString()

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
        // P1 < 24h -> ACTIVE NOW
        created_at: iso(2 * HOUR),
      },
    ],
  },
  total: 1,
}

// A richer fixture exercising all three buckets:
//  - crit:   P0            -> ACTIVE NOW
//  - fresh:  P1 age 2h     -> ACTIVE NOW
//  - stale:  P1 age 48h    -> TODAY (aged-out P1)
//  - mid:    P2 age 1d     -> TODAY
//  - low:    P3            -> LATER
const GROUPED = {
  categories: {
    review: [
      {
        id: 'crit',
        summary: 'Sev0 outage',
        priority: 'P0',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(1 * HOUR),
      },
      {
        id: 'fresh',
        summary: 'Fresh P1 task',
        priority: 'P1',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(2 * HOUR),
      },
      {
        id: 'stale',
        summary: 'Stale P1 task',
        priority: 'P1',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(48 * HOUR),
      },
      {
        id: 'mid',
        summary: 'Mid P2 task',
        priority: 'P2',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(24 * HOUR),
      },
      {
        id: 'low',
        summary: 'Low P3 task',
        priority: 'P3',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(1 * HOUR),
      },
    ],
  },
  total: 5,
}

function overviewBody(efficiencyPeak: number | null = 0.42) {
  return {
    pending_triage: 0,
    in_flight: 0,
    dead_letters: 0,
    active_items: 0,
    sources_enabled: 0,
    sources_total: 0,
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
      throughput: 3,
      efficiency_peak: efficiencyPeak,
      auto_resolved_pct: null,
      avg_triage_seconds: null,
      growth_velocity: null,
      ingestion_success_rate: null,
    },
  }
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/actions', () => HttpResponse.json(ACTIONS)),
    http.get('/api/stats/overview', () => HttpResponse.json(overviewBody())),
    http.get('/api/stats/timeseries', () =>
      HttpResponse.json([
        { bucket: iso(2 * HOUR), count: 1 },
        { bucket: iso(1 * HOUR), count: 2 },
      ]),
    ),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
  localStorage.clear()
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

  it('groups items into ACTIVE NOW / TODAY / LATER buckets', async () => {
    server.use(http.get('/api/actions', () => HttpResponse.json(GROUPED)))
    renderActions()
    expect(await screen.findByText(/Sev0 outage/)).toBeInTheDocument()

    const activeNow = screen.getByRole('region', { name: /active now/i })
    const today = screen.getByRole('region', { name: /^today/i })
    const later = screen.getByRole('region', { name: /^later/i })

    // ACTIVE NOW = P0 or (P1 & age<24h)
    expect(within(activeNow).getByText(/Sev0 outage/)).toBeInTheDocument()
    expect(within(activeNow).getByText(/Fresh P1 task/)).toBeInTheDocument()
    // TODAY = remaining P1 + P2 age<7d
    expect(within(today).getByText(/Stale P1 task/)).toBeInTheDocument()
    expect(within(today).getByText(/Mid P2 task/)).toBeInTheDocument()
    // LATER = P3 + older/snoozed
    expect(within(later).getByText(/Low P3 task/)).toBeInTheDocument()
  })

  it('renders the Throughput card with efficiency_peak as a percent', async () => {
    renderActions()
    const card = await screen.findByTestId('throughput-card')
    expect(within(card).getByText(/throughput/i)).toBeInTheDocument()
    // efficiency_peak 0.42 -> 42% (overview query resolves async)
    expect(await within(card).findByText('42%')).toBeInTheDocument()
  })

  it('renders n/a for efficiency_peak when null', async () => {
    server.use(
      http.get('/api/stats/overview', () =>
        HttpResponse.json(overviewBody(null)),
      ),
    )
    renderActions()
    const card = await screen.findByTestId('throughput-card')
    expect(within(card).getByText('n/a')).toBeInTheDocument()
  })

  it('does not render a hollow active_sessions stat', async () => {
    renderActions()
    await screen.findByText('Fix bug')
    expect(screen.queryByText(/active sessions/i)).not.toBeInTheDocument()
  })

  it('toggles Work Mode and persists it to localStorage', async () => {
    const user = userEvent.setup()
    renderActions()
    const toggle = await screen.findByRole('switch', { name: /work mode/i })
    expect(localStorage.getItem('workbench.workMode')).not.toBe('true')
    await user.click(toggle)
    await waitFor(() =>
      expect(localStorage.getItem('workbench.workMode')).toBe('true'),
    )
  })

  it('focuses on the top active vector and hides chrome when Work Mode is on', async () => {
    localStorage.setItem('workbench.workMode', 'true')
    server.use(http.get('/api/actions', () => HttpResponse.json(GROUPED)))
    renderActions()
    // Top active P0 vector remains visible.
    expect(await screen.findByText(/Sev0 outage/)).toBeInTheDocument()
    // Non-critical groups + widgets hidden while focused.
    expect(screen.queryByText(/Low P3 task/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Mid P2 task/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('throughput-card')).not.toBeInTheDocument()
  })

  it('shows a focused empty state when Work Mode is on and nothing is active', async () => {
    localStorage.setItem('workbench.workMode', 'true')
    server.use(
      http.get('/api/actions', () =>
        HttpResponse.json({
          categories: {
            review: [
              {
                id: 'low',
                summary: 'Low P3 task',
                priority: 'P3',
                parent_item: null,
                action_source: 'manual',
                action_category: 'review',
                created_at: iso(1 * HOUR),
              },
            ],
          },
          total: 1,
        }),
      ),
    )
    renderActions()
    expect(await screen.findByText(/nothing critical/i)).toBeInTheDocument()
  })

  it('creates a manual action via the FAB (POST /api/actions)', async () => {
    const user = userEvent.setup()
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post('/api/actions', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            id: 'new1',
            summary: posted.summary,
            priority: posted.priority ?? 'P2',
            parent_item: null,
            action_source: 'manual',
            action_category: posted.action_category ?? null,
            created_at: iso(0),
          },
          { status: 201 },
        )
      }),
    )
    renderActions()
    await screen.findByText('Fix bug')
    await user.click(screen.getByRole('button', { name: /new action/i }))
    await user.type(screen.getByLabelText(/summary/i), 'Call vendor')
    await user.click(screen.getByRole('button', { name: /^create$/i }))
    await waitFor(() => expect(posted).toMatchObject({ summary: 'Call vendor' }))
    expect(await screen.findByText(/action created/i)).toBeInTheDocument()
  })

  it('surfaces a 422 (blank summary) inline from the FAB', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('/api/actions', () =>
        HttpResponse.json(
          { detail: 'summary must not be empty' },
          { status: 422 },
        ),
      ),
    )
    renderActions()
    await screen.findByText('Fix bug')
    await user.click(screen.getByRole('button', { name: /new action/i }))
    await user.type(screen.getByLabelText(/summary/i), 'x')
    await user.click(screen.getByRole('button', { name: /^create$/i }))
    expect(
      await screen.findByText(/summary must not be empty/i),
    ).toBeInTheDocument()
  })
})
