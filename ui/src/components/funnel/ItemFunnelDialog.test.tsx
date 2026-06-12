import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ItemFunnelDialog } from './ItemFunnelDialog'
import type { FunnelItem } from '@/lib/types/funnel'
import { WBFeedback } from '@/lib/feedback-store'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeItem(overrides: Partial<FunnelItem> = {}): FunnelItem {
  return {
    id: 'item_42',
    summary: 'Fix auth token refresh',
    source: 'github',
    created_at: '2026-06-10T08:00:00Z',
    stages: [
      { filterId: 'fr_01', outcome: 'drop', reason: 'Looks like noise', confidence: 85 },
      { filterId: 'fr_02', outcome: 'pass', reason: 'No match' },
      { filterId: 'fr_03', outcome: 'include', reason: 'Security related', confidence: 93 },
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
  { id: 'fr_01', prompt: 'Drop bot-generated noise' },
  { id: 'fr_02', prompt: 'Skip calendar invites' },
  { id: 'fr_03', prompt: 'Include security patches' },
]

beforeEach(() => {
  WBFeedback.state.overrides = []
  WBFeedback.state.tasks = []
  WBFeedback.state.promptPatches = {}
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ItemFunnelDialog', () => {
  it('renders nothing when open is false', () => {
    const { container } = render(
      <ItemFunnelDialog
        item={makeItem()}
        open={false}
        onClose={() => {}}
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when item is null', () => {
    const { container } = render(
      <ItemFunnelDialog
        item={null}
        open={true}
        onClose={() => {}}
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders dialog with item summary and ID', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
        filterRules={FILTER_RULES}
      />,
    )
    expect(screen.getByTestId('funnel-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('dialog-title')).toHaveTextContent('Fix auth token refresh')
    expect(screen.getByTestId('dialog-title')).toHaveTextContent('item_42')
  })

  it('shows the source icon and type', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('github')).toBeInTheDocument()
  })

  it('renders VerdictPill with correct decision', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
      />,
    )
    // Portal renders into document.body; query globally
    expect(document.querySelector('[data-verdict="triaged"]')).toBeInTheDocument()
  })

  it('renders treatment log header with enricher and filter counts', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
      />,
    )
    const header = screen.getByTestId('treatment-log-header')
    expect(header).toHaveTextContent('0 enrichers')
    expect(header).toHaveTextContent('3 filters')
    expect(header).toHaveTextContent('ms total')
  })

  it('renders all FunnelStage components', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
        filterRules={FILTER_RULES}
      />,
    )
    const stages = screen.getAllByTestId('funnel-stage')
    expect(stages).toHaveLength(3)
  })

  it('renders aggregated verdict section', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
        filterRules={FILTER_RULES}
      />,
    )
    const verdict = screen.getByTestId('aggregated-verdict')
    expect(verdict).toHaveTextContent('Aggregated verdict')
    expect(verdict).toHaveTextContent('LLM joined')
    expect(verdict).toHaveTextContent('Security-relevant diff that needs human review.')
  })

  it('shows contributing signals in aggregated verdict', () => {
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={() => {}}
        filterRules={FILTER_RULES}
      />,
    )
    // Should show signals for drop (85%) and include (93%)
    const verdictSection = screen.getByTestId('aggregated-verdict')
    expect(verdictSection.querySelector('[data-action="drop"]')).toBeInTheDocument()
    expect(verdictSection.querySelector('[data-action="include"]')).toBeInTheDocument()
  })

  it('calls onClose when overlay is clicked', () => {
    const onClose = vi.fn()
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={onClose}
      />,
    )
    fireEvent.mouseDown(screen.getByTestId('funnel-dialog-overlay'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose when dialog body is clicked', () => {
    const onClose = vi.fn()
    render(
      <ItemFunnelDialog
        item={makeItem()}
        open={true}
        onClose={onClose}
      />,
    )
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
    render(
      <ItemFunnelDialog
        item={item}
        open={true}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/carried forward/)).toBeInTheDocument()
  })
})
