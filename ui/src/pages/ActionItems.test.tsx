// Action Items page tests (spec Design Section 2.3, v3 design upgrade).
//
// Mirrors Sources.test.tsx: a local render helper with QueryClientProvider +
// MemoryRouter + Toaster, driven through MSW. Covers the five UI states plus the
// three lifecycle mutations (mark-done POST, change-priority POST, snooze POST)
// each hitting MSW and showing a sonner toast. Work Mode was removed in v3;
// throughput chart and filter tuning section are tested instead.

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
        id: 42,
        summary: 'Fix bug',
        priority: 'P1',
        path: '1.1.1',
        parent_item: { id: 1, summary: 'Parent thread' },
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
        id: 1,
        summary: 'Sev0 outage',
        priority: 'P0',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(1 * HOUR),
      },
      {
        id: 2,
        summary: 'Fresh P1 task',
        priority: 'P1',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(2 * HOUR),
      },
      {
        id: 3,
        summary: 'Stale P1 task',
        priority: 'P1',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(48 * HOUR),
      },
      {
        id: 4,
        summary: 'Mid P2 task',
        priority: 'P2',
        parent_item: null,
        action_source: 'manual',
        action_category: 'review',
        created_at: iso(24 * HOUR),
      },
      {
        id: 5,
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

function timeseriesBody(counts: number[]) {
  return counts.map((c, i) => ({
    bucket: iso((counts.length - i) * HOUR),
    count: c,
  }))
}

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/actions', () => HttpResponse.json(ACTIONS)),
    http.get('/api/stats/overview', () => HttpResponse.json(overviewBody())),
    http.get('/api/stats/timeseries', ({ request }) => {
      const url = new URL(request.url)
      const metric = url.searchParams.get('metric')
      if (metric === 'incoming_actions') {
        return HttpResponse.json(timeseriesBody([2, 3, 5, 4, 6, 7, 5, 8, 6, 7, 9, 6]))
      }
      if (metric === 'completion_rate') {
        return HttpResponse.json(timeseriesBody([1, 2, 3, 4, 5, 5, 6, 6, 7, 6, 7, 8]))
      }
      return HttpResponse.json(timeseriesBody([1, 2]))
    }),
    http.get('/api/feedback/tasks', ({ request }) => {
      const url = new URL(request.url)
      const status = url.searchParams.get('status')
      if (status === 'open') {
        return HttpResponse.json([])
      }
      return HttpResponse.json([])
    }),
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
      name: /set priority for 42/i,
    }) as HTMLSelectElement
    expect(prioritySelect.value).toBe('P1')
  })

  it('opens the item detail dialog for an action', async () => {
    renderActions()
    const btn = await screen.findByRole('button', { name: '#42' })
    expect(btn).toBeInTheDocument()
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
      http.post('/api/actions/42/done', () => {
        done = true
        return HttpResponse.json({ status: 'done' })
      }),
    )
    renderActions()
    await userEvent.click(
      await screen.findByRole('button', { name: /mark 42 done/i }),
    )
    await waitFor(() => expect(done).toBe(true))
    expect(await screen.findByText(/marked done/i)).toBeInTheDocument()
  })

  it('change priority calls POST /priority with the chosen value', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers(),
      http.post('/api/actions/42/priority', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'updated', priority: posted.priority })
      }),
    )
    renderActions()
    const select = await screen.findByRole('combobox', {
      name: /set priority for 42/i,
    })
    await userEvent.selectOptions(select, 'P0')
    await waitFor(() => expect(posted).toMatchObject({ priority: 'P0' }))
  })

  it('snooze calls POST /snooze with hours', async () => {
    let posted: Record<string, unknown> | null = null
    server.use(
      ...baseHandlers(),
      http.post('/api/actions/42/snooze', async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ status: 'snoozed', hours: posted.hours })
      }),
    )
    renderActions()
    await userEvent.click(
      await screen.findByRole('button', { name: /snooze 42/i }),
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

  it('does not render a hollow active_sessions stat', async () => {
    renderActions()
    await screen.findByText('Fix bug')
    expect(screen.queryByText(/active sessions/i)).not.toBeInTheDocument()
  })

  // --- Work Mode removed in v3 ---

  it('does not render Work Mode toggle or Terminal Focus', async () => {
    renderActions()
    await screen.findByText('Fix bug')
    expect(screen.queryByRole('switch', { name: /work mode/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/terminal focus/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/WORK_MODE_ON/i)).not.toBeInTheDocument()
  })

  // --- Throughput chart ---

  it('renders the throughput chart card with MultiLineChart', async () => {
    renderActions()
    const card = await screen.findByTestId('throughput-chart-card')
    expect(within(card).getByText(/throughput/i)).toBeInTheDocument()
    // Wait for the timeseries data to load and render the chart
    expect(await within(card).findByTestId('multi-line-chart')).toBeInTheDocument()
  })

  // --- Filter Tuning section ---

  it('does not render filter tuning section when no open tasks exist', async () => {
    renderActions()
    await screen.findByText('Fix bug')
    expect(screen.queryByTestId('filter-tuning-section')).not.toBeInTheDocument()
  })

  it('renders filter tuning section when server has open tasks', async () => {
    server.use(
      http.get('/api/feedback/tasks', ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get('status')
        if (status === 'open') {
          return HttpResponse.json([
            {
              id: 1,
              rule_id: 42,
              filter_id: 'filter-spam',
              item_id: 101,
              item_summary: 'Test item',
              from_outcome: 'drop',
              to_outcome: 'include',
              from_label: null,
              to_label: null,
              filter_prompt: 'Drop spam items',
              proposed_prompt: 'Drop spam items — but keep genuine items like "Test item"',
              kind: 'filter-tuning',
              correction_ids: [],
              status: 'open',
              created_at: iso(1 * HOUR),
              resolved_at: null,
            },
          ])
        }
        return HttpResponse.json([])
      }),
    )
    renderActions()
    const section = await screen.findByTestId('filter-tuning-section')
    expect(section).toBeInTheDocument()
    expect(within(section).getByTestId('filter-tuning-card')).toBeInTheDocument()
  })

  it('highlights the tuning card targeted by ?tuning=<id>', async () => {
    server.use(
      http.get('/api/feedback/tasks', ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get('status')
        if (status === 'open') {
          return HttpResponse.json([
            {
              id: 99,
              rule_id: 42,
              filter_id: 'filter-spam',
              item_id: 101,
              item_summary: 'Test item',
              from_outcome: 'drop',
              to_outcome: 'include',
              from_label: null,
              to_label: null,
              filter_prompt: 'Drop spam items',
              proposed_prompt: 'Drop spam items — but keep genuine items',
              kind: 'filter-tuning',
              correction_ids: [],
              status: 'open',
              created_at: iso(1 * HOUR),
              resolved_at: null,
            },
          ])
        }
        return HttpResponse.json([])
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, refetchInterval: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/actions?tuning=99']}>
          <ActionItems />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const card = await screen.findByTestId('filter-tuning-card')
    expect(card).toHaveAttribute('data-highlighted', 'true')
  })

  it('applies a tuning task: PATCH prompt then PATCH status', async () => {
    let patchedPrompt: unknown = null
    let patchedStatus: string | null = null
    server.use(
      http.get('/api/feedback/tasks', ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get('status')
        if (status === 'open') {
          return HttpResponse.json([
            {
              id: 55,
              rule_id: 10,
              filter_id: 'fr_10',
              item_id: 202,
              item_summary: 'Apply test item',
              from_outcome: 'drop',
              to_outcome: 'include',
              from_label: null,
              to_label: null,
              filter_prompt: 'Old prompt',
              proposed_prompt: 'New improved prompt',
              kind: 'filter-tuning',
              correction_ids: [],
              status: 'open',
              created_at: iso(1 * HOUR),
              resolved_at: null,
            },
          ])
        }
        return HttpResponse.json([])
      }),
      http.patch('/api/filter-rules/10/prompt', async ({ request }) => {
        patchedPrompt = await request.json()
        return HttpResponse.json({ status: 'updated' })
      }),
      http.patch('/api/feedback/tasks/55', ({ request }) => {
        const url = new URL(request.url)
        patchedStatus = url.searchParams.get('status')
        return HttpResponse.json({
          id: 55,
          status: patchedStatus,
          resolved_at: iso(0),
        })
      }),
    )
    renderActions()
    const section = await screen.findByTestId('filter-tuning-section')
    await userEvent.click(within(section).getByTestId('apply-button'))
    await waitFor(() => expect(patchedPrompt).toMatchObject({ prompt: 'New improved prompt' }))
    expect(patchedStatus).toBe('applied')
  })

  // --- New action button (header, not FAB) ---

  it('creates a manual action via the header button (POST /api/actions)', async () => {
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

  it('surfaces a 422 (blank summary) inline from the create dialog', async () => {
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
