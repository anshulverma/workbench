// FilterDetailDialog tests — server-backed corrections display.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FilterDetailDialog } from './FilterDetailDialog'
import type { FilterRuleExtended, FunnelItem } from '@/lib/types/funnel'
import { _resetToken } from '@/lib/api'

// ---- Test data ----

const FILTER_RULE: FilterRuleExtended = {
  id: 1,
  prompt: 'Drop CI notifications about passing builds',
  action: 'drop',
  label: undefined,
  sources: ['github'],
  confidence: 92,
  origin: 'learned',
  matched: 14,
  enabled: true,
  order_index: 0,
}

const FUNNEL_ITEMS: FunnelItem[] = [
  {
    id: 101,
    summary: 'PR #42: Fix login bug',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [
      {
        filterId: '1',
        outcome: 'drop',
        reason: 'CI notification.',
        confidence: 95,
      },
    ],
    verdict: {
      decision: 'dropped',
      priority: undefined,
      confidence: 95,
      rationale: 'Automated CI notification.',
    },
  },
  {
    id: 102,
    summary: 'PR #99: Update deps',
    source: 'github',
    created_at: '2026-06-11T08:00:00Z',
    stages: [
      {
        filterId: '1',
        outcome: 'pass',
        reason: 'Not a CI notification.',
        confidence: 88,
      },
    ],
    verdict: {
      decision: 'triaged',
      priority: 'P2',
      confidence: 88,
      rationale: 'Relevant dependency update.',
    },
  },
]

const CORRECTIONS = [
  {
    id: 201,
    item_id: 102,
    rule_id: null,
    filter_id: '1',
    item_summary: 'PR #99: Update deps',
    original_action: 'pass',
    corrected_action: 'drop',
    from_label: null,
    to_label: null,
    reason: null,
    created_at: '2026-06-11T09:00:00Z',
  } as const,
]

// ---- MSW ----

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/feedback/corrections', () =>
      HttpResponse.json(CORRECTIONS),
    ),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

function renderDialog(rule: FilterRuleExtended | null = FILTER_RULE) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <FilterDetailDialog
        rule={rule}
        items={FUNNEL_ITEMS}
        onOpenItem={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

// ---- Tests ----

describe('FilterDetailDialog', () => {
  it('renders nothing when rule is null', () => {
    const { container } = renderDialog(null)
    expect(container.innerHTML).toBe('')
  })

  it('renders the dialog with rule prompt and ID', async () => {
    renderDialog()
    expect(
      await screen.findByTestId('filter-detail-dialog'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Drop CI notifications about passing builds/),
    ).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('shows corrections summary for the filter', async () => {
    renderDialog()
    const summary = await screen.findByTestId('corrections-summary')
    expect(
      within(summary).getByText(/changed this filter's classification/i),
    ).toBeInTheDocument()
    expect(within(summary).getByText(/1 item/)).toBeInTheDocument()
    expect(
      within(summary).getByText('PR #99: Update deps'),
    ).toBeInTheDocument()
  })

  it('displays items processed by the filter', async () => {
    renderDialog()
    await screen.findByTestId('filter-detail-dialog')
    expect(screen.getByText('PR #42: Fix login bug')).toBeInTheDocument()
    expect(screen.getByText('PR #99: Update deps')).toBeInTheDocument()
  })

  it('shows corrected action for items with corrections', async () => {
    renderDialog()
    const dialog = await screen.findByTestId('filter-detail-dialog')
    // Wait for corrections to load
    await screen.findByTestId('corrections-summary')
    // Item 102 has a correction from pass → drop
    const rows = within(dialog).getAllByRole('row')
    const item102Row = rows.find((r) =>
      r.textContent?.includes('PR #99: Update deps'),
    )
    expect(item102Row).toBeDefined()
    expect(item102Row?.textContent).toContain('corrected')
  })
})
