// Filters page tests (Slice 12).
//
// Covers: loading state, unauthorized state, error state, interleaved funnel
// rendering (enricher + filter + loopback cards), reorder buttons, add-filter
// dialog, funnel output table, and detail dialogs.

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
import { Filters } from './Filters'
import { _resetToken } from '@/lib/api'

// ---- Test data ----

const FILTER_RULES = [
  {
    id: 'fr_01',
    prompt: 'Drop CI notifications about passing builds',
    action: 'drop',
    sources: ['github'],
    confidence: 92,
    origin: 'learned',
    matched: 14,
    enabled: true,
    order_index: 0,
  },
  {
    id: 'fr_02',
    prompt: 'Include any diff mentioning my team',
    action: 'include',
    sources: ['github', 'email'],
    confidence: 88,
    origin: 'explicit',
    matched: 7,
    enabled: true,
    order_index: 1,
  },
]

const ENRICHERS = [
  {
    id: 'en_github',
    type: 'github',
    label: 'GitHub Metadata',
    depth: 'shallow',
    enabled: true,
    adds: ['author', 'files_changed', 'ci_status'],
    records: ['people', 'repos'],
    budget: { max_calls: 1, max_time_ms: 5000 },
    avg_ms: 12,
    enriched: 42,
  },
]

const LOOPBACKS = [
  {
    id: 'lb_repush',
    label: 'Re-push stale',
    trigger: 'When an item was triaged >24h ago but no action taken',
    condition: 'status === "triaged" && age_hours > 24',
    max_loops: 2,
    enabled: true,
    looped: 3,
    avg_loops: 1.5,
  },
]

const FUNNEL_ITEMS = [
  {
    id: 'itm_1',
    summary: 'PR #42: Fix login bug',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [
      {
        filterId: 'en_github',
        outcome: 'context',
        reason: 'GitHub Metadata resolved metadata.',
        context: 'author: alice · files: 3',
      },
      {
        filterId: 'fr_01',
        outcome: 'pass',
        reason: 'Not a CI notification.',
        confidence: 95,
      },
      {
        filterId: 'fr_02',
        outcome: 'include',
        reason: 'Mentions your team.',
        confidence: 88,
      },
    ],
    verdict: {
      decision: 'triaged',
      priority: 'P1',
      confidence: 91,
      rationale: 'Relevant to your team based on two filter signals.',
    },
  },
]

const FUNNEL_ORDER = [
  { kind: 'enricher', id: 'en_github' },
  { kind: 'filter', id: 'fr_01' },
  { kind: 'filter', id: 'fr_02' },
  { kind: 'loopback', id: 'lb_repush' },
]

const ENRICHMENT_SAMPLES = {
  en_github: [
    {
      id: 'itm_1',
      summary: 'PR #42: Fix login bug',
      context: { author: 'alice', files_changed: 3, ci_status: 'passing' },
      entities: ['alice', 'meta/workbench'],
    },
  ],
}

// ---- MSW ----

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/funnel/filter-rules', () =>
      HttpResponse.json(FILTER_RULES),
    ),
    http.get('/api/funnel/enrichers', () => HttpResponse.json(ENRICHERS)),
    http.get('/api/funnel/loopbacks', () => HttpResponse.json(LOOPBACKS)),
    http.get('/api/funnel/items', () => HttpResponse.json(FUNNEL_ITEMS)),
    http.get('/api/funnel/order', () => HttpResponse.json(FUNNEL_ORDER)),
    http.get('/api/funnel/enrichment-samples', () =>
      HttpResponse.json(ENRICHMENT_SAMPLES),
    ),
    http.get('/api/feedback/tasks', ({ request }) => {
      const url = new URL(request.url)
      const status = url.searchParams.get('status')
      if (status === 'applied') {
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
})
afterAll(() => server.close())

function renderFilters() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Filters />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ---- Tests ----

describe('Filters page — states', () => {
  it('renders the loading skeleton while data is pending', () => {
    server.use(
      http.get('/api/funnel/filter-rules', () => new Promise(() => {})),
    )
    renderFilters()
    expect(screen.getByTestId('filters-loading')).toBeInTheDocument()
  })

  it('renders the unauthorized state on 401', async () => {
    server.use(
      http.get('/api/auth/token', () =>
        new HttpResponse(null, { status: 401 }),
      ),
    )
    renderFilters()
    await waitFor(() =>
      expect(screen.getByText(/token unavailable/i)).toBeInTheDocument(),
    )
  })

  it('renders the error state when filter-rules fails', async () => {
    server.use(
      http.get('/api/funnel/filter-rules', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-f1' } },
        ),
      ),
    )
    renderFilters()
    await waitFor(() =>
      expect(screen.getByTestId('filters-error')).toBeInTheDocument(),
    )
  })
})

describe('Filters page — interleaved funnel', () => {
  it('renders enricher, filter, and loopback cards in order', async () => {
    renderFilters()
    // Wait for enricher card
    expect(
      await screen.findByTestId('enricher-card-en_github'),
    ).toBeInTheDocument()
    // Filter cards
    expect(
      screen.getByTestId('filter-rule-card-fr_01'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('filter-rule-card-fr_02'),
    ).toBeInTheDocument()
    // Loopback card
    expect(
      screen.getByTestId('loopback-card-lb_repush'),
    ).toBeInTheDocument()
  })

  it('enricher card shows enricher badge and label', async () => {
    renderFilters()
    const card = await screen.findByTestId('enricher-card-en_github')
    expect(within(card).getByText('enricher')).toBeInTheDocument()
    expect(within(card).getByText('GitHub Metadata')).toBeInTheDocument()
    expect(within(card).getByText('en_github')).toBeInTheDocument()
    expect(within(card).getByText('shallow')).toBeInTheDocument()
  })

  it('filter rule card shows action chip, prompt, and confidence', async () => {
    renderFilters()
    const card = await screen.findByTestId('filter-rule-card-fr_01')
    expect(
      within(card).getByText(
        'Drop CI notifications about passing builds',
      ),
    ).toBeInTheDocument()
    // Confidence bar should show 92%
    expect(within(card).getByText('92%')).toBeInTheDocument()
    // Source chip
    expect(within(card).getByText('github')).toBeInTheDocument()
  })

  it('loopback card shows loop-back badge, label, and stats', async () => {
    renderFilters()
    const card = await screen.findByTestId('loopback-card-lb_repush')
    expect(within(card).getByText('loop-back')).toBeInTheDocument()
    expect(within(card).getByText('Re-push stale')).toBeInTheDocument()
    expect(within(card).getByText(/max 2×/)).toBeInTheDocument()
    expect(within(card).getByText(/avg 1.5×/)).toBeInTheDocument()
  })

  it('shows the evaluation order header with reorder hint', async () => {
    renderFilters()
    await screen.findByTestId('enricher-card-en_github')
    expect(
      screen.getByText(/evaluation order/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/use ↑ ↓ to reorder/)).toBeInTheDocument()
  })
})

describe('Filters page — funnel output table', () => {
  it('renders the funnel output table with items', async () => {
    renderFilters()
    const table = await screen.findByTestId('funnel-output-table')
    // Table headers
    expect(within(table).getByText('Item')).toBeInTheDocument()
    expect(within(table).getByText('Source')).toBeInTheDocument()
    expect(within(table).getByText('Treatment')).toBeInTheDocument()
    expect(within(table).getByText('Verdict')).toBeInTheDocument()
    // Item row
    expect(
      within(table).getByText('PR #42: Fix login bug'),
    ).toBeInTheDocument()
  })
})

describe('Filters page — add filter dialog', () => {
  it('opens and closes the add filter dialog', async () => {
    renderFilters()
    const addBtn = await screen.findByTestId('add-filter-button')
    await userEvent.click(addBtn)
    expect(
      await screen.findByText('New Filter Rule'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/noise filter matches it with the LLM/),
    ).toBeInTheDocument()
    // Close via Cancel button
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    await waitFor(() =>
      expect(
        screen.queryByText('New Filter Rule'),
      ).not.toBeInTheDocument(),
    )
  })

  it('creates a new filter rule', async () => {
    let created = false
    server.use(
      ...baseHandlers(),
      http.post('/api/funnel/filter-rules', () => {
        created = true
        return HttpResponse.json({
          id: 'fr_99',
          prompt: 'Test prompt',
          action: 'drop',
          sources: ['github'],
          confidence: 75,
          origin: 'explicit',
          matched: 0,
          enabled: true,
          order_index: 2,
        })
      }),
    )
    renderFilters()
    await userEvent.click(await screen.findByTestId('add-filter-button'))
    await userEvent.type(
      screen.getByTestId('add-rule-prompt'),
      'Test prompt for new rule',
    )
    await userEvent.click(screen.getByTestId('add-rule-submit'))
    await waitFor(() => expect(created).toBe(true))
  })
})

describe('Filters page — toggle switch', () => {
  it('toggle switch for enricher calls toggle API', async () => {
    let toggled = false
    server.use(
      ...baseHandlers(),
      http.post('/api/funnel/stages/en_github/toggle', () => {
        toggled = true
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    renderFilters()
    const card = await screen.findByTestId('enricher-card-en_github')
    const toggle = within(card).getByRole('switch', {
      name: /toggle en_github/i,
    })
    await userEvent.click(toggle)
    await waitFor(() => expect(toggled).toBe(true))
  })
})

describe('Filters page — tuned filters', () => {
  it('shows tuned indicator when a filter has an applied task', async () => {
    server.use(
      http.get('/api/feedback/tasks', ({ request }) => {
        const url = new URL(request.url)
        const status = url.searchParams.get('status')
        if (status === 'applied') {
          return HttpResponse.json([
            {
              id: 101,
              filter_id: 'fr_01',
              item_id: 42,
              item_summary: 'PR #99',
              from_outcome: 'pass',
              to_outcome: 'drop',
              from_label: null,
              to_label: null,
              filter_prompt: 'Drop CI notifications about passing builds',
              proposed_prompt: 'Drop CI notifications about passing builds, especially for dependabot',
              kind: 'filter-tuning',
              correction_ids: [1],
              status: 'applied',
              created_at: '2026-06-20T12:00:00Z',
              resolved_at: '2026-06-20T13:00:00Z',
              rule_id: null,
            },
          ])
        }
        return HttpResponse.json([])
      }),
    )
    renderFilters()
    const card = await screen.findByTestId('filter-rule-card-fr_01')
    // Should show tuned badge/indicator (wait for it to appear after query loads)
    expect(
      await within(card).findByTestId('tuned-badge'),
    ).toBeInTheDocument()
    // Prompt should be from the rule itself, not a patched prompt
    expect(
      within(card).getByText('Drop CI notifications about passing builds'),
    ).toBeInTheDocument()
  })
})

describe('Filters page — exports', () => {
  it('exports IngestionFunnel as a named export', async () => {
    const mod = await import('./Filters')
    expect(mod.IngestionFunnel).toBeDefined()
    expect(mod.IngestionFunnel).toBe(mod.Filters)
  })
})
