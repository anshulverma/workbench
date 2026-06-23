import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ItemFunnelDialog } from './ItemFunnelDialog'
import type { FunnelItem } from '@/lib/types/funnel'
import { _resetToken } from '@/lib/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeItem(overrides: Partial<FunnelItem> = {}): FunnelItem {
  return {
    id: 42,
    summary: 'Fix auth token refresh',
    source: 'github',
    created_at: '2026-06-10T08:00:00Z',
    stages: [
      { filterId: '1', outcome: 'drop', reason: 'Looks like noise', confidence: 85 },
      { filterId: '2', outcome: 'pass', reason: 'No match' },
      { filterId: '3', outcome: 'include', reason: 'Security related', confidence: 93 },
    ],
    verdict: {
      decision: 'triaged',
      priority: 'P1',
      confidence: 90,
      rationale: 'Security-relevant diff that needs human review.',
    },
    ...overrides,
  }
}

const FILTER_RULES = [
  { id: 1, prompt: 'Drop bot-generated noise' },
  { id: 2, prompt: 'Skip calendar invites' },
  { id: 3, prompt: 'Include security patches' },
]

// ---- MSW ----

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/feedback/corrections', () => HttpResponse.json([])),
    http.get('/api/feedback/tasks', () => HttpResponse.json([])),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(...baseHandlers())
  _resetToken()
})
afterAll(() => server.close())

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function renderDialog(props: Partial<React.ComponentProps<typeof ItemFunnelDialog>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
        filterRules={FILTER_RULES}
        {...props}
      />
    </QueryClientProvider>,
  )
}

describe('ItemFunnelDialog', () => {
  it('renders nothing when open is false', () => {
    const { container } = renderDialog({ open: false })
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when item is null', () => {
    const { container } = renderDialog({ item: null })
    expect(container.innerHTML).toBe('')
  })

  it('renders dialog with item summary and ID', () => {
    renderDialog()
    expect(screen.getByTestId('funnel-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('dialog-title')).toHaveTextContent('Fix auth token refresh')
    expect(screen.getByTestId('dialog-title')).toHaveTextContent('42')
  })

  it('shows the source icon and type', () => {
    renderDialog()
    expect(screen.getByText('github')).toBeInTheDocument()
  })

  it('renders VerdictPill with correct decision', () => {
    renderDialog()
    // Portal renders into document.body; query globally
    expect(document.querySelector('[data-verdict="triaged"]')).toBeInTheDocument()
  })

  it('renders treatment log header with enricher and filter counts', () => {
    renderDialog()
    const header = screen.getByTestId('treatment-log-header')
    expect(header).toHaveTextContent('0 enrichers')
    expect(header).toHaveTextContent('3 filters')
    expect(header).toHaveTextContent('ms total')
  })

  it('renders all FunnelStage components', () => {
    renderDialog()
    const stages = screen.getAllByTestId('funnel-stage')
    expect(stages).toHaveLength(3)
  })

  it('renders aggregated verdict section', () => {
    renderDialog()
    const verdict = screen.getByTestId('aggregated-verdict')
    expect(verdict).toHaveTextContent('Aggregated verdict')
    expect(verdict).toHaveTextContent('LLM joined')
    expect(verdict).toHaveTextContent('Security-relevant diff that needs human review.')
  })

  it('shows contributing signals in aggregated verdict', () => {
    renderDialog()
    // Should show signals for drop (85%) and include (93%)
    const verdictSection = screen.getByTestId('aggregated-verdict')
    expect(verdictSection.querySelector('[data-action="drop"]')).toBeInTheDocument()
    expect(verdictSection.querySelector('[data-action="include"]')).toBeInTheDocument()
  })

  it('calls onClose when overlay is clicked', () => {
    const onClose = vi.fn()
    renderDialog({ onClose })
    fireEvent.mouseDown(screen.getByTestId('funnel-dialog-overlay'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    renderDialog({ onClose })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose when dialog body is clicked', () => {
    const onClose = vi.fn()
    renderDialog({ onClose })
    fireEvent.mouseDown(screen.getByTestId('funnel-dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('shows carried-forward contexts when present', () => {
    const item = makeItem({
      stages: [
        { filterId: 'fr_01', outcome: 'drop', confidence: 85, context: 'author: alice' },
        { filterId: 'fr_02', outcome: 'include', confidence: 93, context: 'ci: passing' },
      ],
    })
    renderDialog({ item })
    expect(screen.getByText(/carried forward/)).toBeInTheDocument()
  })
})
