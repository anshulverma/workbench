import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FunnelStage } from './FunnelStage'
import type { FunnelStage as FunnelStageType, FunnelItem } from '@/lib/types/funnel'
import { WBFeedback } from '@/lib/feedback-store'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStage(overrides: Partial<FunnelStageType> = {}): FunnelStageType {
  return {
    filterId: 'fr_01',
    outcome: 'drop',
    reason: 'Matched auto-drop pattern',
    confidence: 92,
    ...overrides,
  }
}

function makeItem(overrides: Partial<FunnelItem> = {}): FunnelItem {
  return {
    id: 'item_1',
    summary: 'Test PR #42',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [makeStage()],
    verdict: { decision: 'dropped', rationale: 'auto-dropped', confidence: 92 },
    ...overrides,
  }
}

// Clean feedback store between tests
beforeEach(() => {
  WBFeedback.state.overrides = []
  WBFeedback.state.tasks = []
  WBFeedback.state.promptPatches = {}
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FunnelStage', () => {
  it('renders stage with order number and filterId', () => {
    render(
      <FunnelStage stage={makeStage()} index={0} isLast={false} />,
    )
    expect(screen.getByText(/01 · fr_01/)).toBeInTheDocument()
  })

  it('renders the ActionChip with the stage outcome', () => {
    const { container } = render(
      <FunnelStage stage={makeStage({ outcome: 'drop' })} index={0} isLast={false} />,
    )
    expect(container.querySelector('[data-action="drop"]')).toBeInTheDocument()
  })

  it('shows connecting line when not last', () => {
    render(
      <FunnelStage stage={makeStage()} index={0} isLast={false} />,
    )
    expect(screen.getByTestId('connecting-line')).toBeInTheDocument()
  })

  it('hides connecting line when last', () => {
    render(
      <FunnelStage stage={makeStage()} index={2} isLast={true} />,
    )
    expect(screen.queryByTestId('connecting-line')).not.toBeInTheDocument()
  })

  it('shows enricher badge for enricher stages', () => {
    render(
      <FunnelStage
        stage={makeStage({ filterId: 'en_github', outcome: 'context' })}
        index={0}
        isLast={false}
      />,
    )
    expect(screen.getByTestId('enricher-badge')).toBeInTheDocument()
    expect(screen.getByText(/enricher/)).toBeInTheDocument()
  })

  it('does not show enricher badge for filter stages', () => {
    render(
      <FunnelStage stage={makeStage({ filterId: 'fr_01' })} index={0} isLast={false} />,
    )
    expect(screen.queryByTestId('enricher-badge')).not.toBeInTheDocument()
  })

  it('shows timing info when provided', () => {
    render(
      <FunnelStage
        stage={makeStage()}
        index={0}
        isLast={false}
        timing={{ at: 50, dur: 80 }}
      />,
    )
    const timingEl = screen.getByTestId('timing-info')
    expect(timingEl).toHaveTextContent('+50ms')
    expect(timingEl).toHaveTextContent('80ms')
  })

  it('does not show timing info when not provided', () => {
    render(
      <FunnelStage stage={makeStage()} index={0} isLast={false} />,
    )
    expect(screen.queryByTestId('timing-info')).not.toBeInTheDocument()
  })

  it('shows correct button when editable and item provided', () => {
    render(
      <FunnelStage
        stage={makeStage()}
        index={0}
        isLast={false}
        item={makeItem()}
        editable
      />,
    )
    expect(screen.getByTestId('correct-button')).toBeInTheDocument()
    expect(screen.getByText('correct')).toBeInTheDocument()
  })

  it('does not show correct button for enricher stages even when editable', () => {
    render(
      <FunnelStage
        stage={makeStage({ filterId: 'en_github', outcome: 'context' })}
        index={0}
        isLast={false}
        item={makeItem()}
        editable
      />,
    )
    expect(screen.queryByTestId('correct-button')).not.toBeInTheDocument()
  })

  it('opens correction picker on correct click', () => {
    render(
      <FunnelStage
        stage={makeStage({ outcome: 'drop' })}
        index={0}
        isLast={false}
        item={makeItem()}
        editable
      />,
    )
    fireEvent.click(screen.getByTestId('correct-button'))
    expect(screen.getByTestId('correction-picker')).toBeInTheDocument()
    expect(screen.getByText('This should have been...')).toBeInTheDocument()
    // Should not show the current outcome as a choice
    expect(screen.queryByText('Drop')).not.toBeInTheDocument()
    expect(screen.getByText('Keep / include')).toBeInTheDocument()
  })

  it('applies correction and shows override display', () => {
    const item = makeItem()
    const { rerender } = render(
      <FunnelStage
        stage={makeStage({ outcome: 'drop' })}
        index={0}
        isLast={false}
        item={item}
        editable
      />,
    )
    fireEvent.click(screen.getByTestId('correct-button'))
    fireEvent.click(screen.getByText('Keep / include'))

    // Re-render to pick up store change
    rerender(
      <FunnelStage
        stage={makeStage({ outcome: 'drop' })}
        index={0}
        isLast={false}
        item={item}
        editable
      />,
    )

    expect(screen.getByTestId('override-display')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-receipt')).toBeInTheDocument()
    expect(screen.getByTestId('undo-button')).toBeInTheDocument()
  })

  it('removes override on undo click', () => {
    const item = makeItem()
    // Pre-populate override
    WBFeedback.addOverride({
      itemId: item.id,
      itemSummary: item.summary,
      filterId: 'fr_01',
      filterPrompt: 'test prompt',
      fromOutcome: 'drop',
      toOutcome: 'include',
    })

    const { rerender } = render(
      <FunnelStage
        stage={makeStage({ outcome: 'drop' })}
        index={0}
        isLast={false}
        item={item}
        editable
      />,
    )

    expect(screen.getByTestId('undo-button')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('undo-button'))

    rerender(
      <FunnelStage
        stage={makeStage({ outcome: 'drop' })}
        index={0}
        isLast={false}
        item={item}
        editable
      />,
    )

    expect(screen.queryByTestId('override-display')).not.toBeInTheDocument()
    expect(screen.getByTestId('correct-button')).toBeInTheDocument()
  })

  it('shows context badge when stage has context', () => {
    render(
      <FunnelStage
        stage={makeStage({ context: 'author: alice · files: 3' })}
        index={0}
        isLast={false}
      />,
    )
    expect(screen.getByTestId('context-badge')).toBeInTheDocument()
    expect(screen.getByText('author: alice · files: 3')).toBeInTheDocument()
  })

  it('shows reason text', () => {
    render(
      <FunnelStage
        stage={makeStage({ reason: 'This matches the noise pattern' })}
        index={0}
        isLast={false}
      />,
    )
    expect(screen.getByText('This matches the noise pattern')).toBeInTheDocument()
  })

  it('shows weak indicator when stage is weak', () => {
    render(
      <FunnelStage
        stage={makeStage({ weak: true })}
        index={0}
        isLast={false}
      />,
    )
    expect(screen.getByText(/weak · below threshold/)).toBeInTheDocument()
  })
})
