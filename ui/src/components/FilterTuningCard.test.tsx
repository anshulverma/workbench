import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FilterTuningCard } from './FilterTuningCard'
import type { FilterTuningTask } from '@/lib/types/feedback'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTask(overrides: Partial<FilterTuningTask> = {}): FilterTuningTask {
  return {
    id: 'act_ft_abc12',
    kind: 'filter-tuning',
    status: 'open',
    itemId: 'item_42',
    itemSummary: 'Fix auth token refresh',
    filterId: 'fr_01',
    filterPrompt: 'Drop bot-generated noise',
    fromOutcome: 'drop',
    toOutcome: 'include',
    proposedPrompt:
      'Drop bot-generated noise — but kept and surfaced cases like "Fix auth token refresh" (you corrected this).',
    at: Date.now(),
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FilterTuningCard', () => {
  it('renders the card with task data', () => {
    render(
      <FilterTuningCard
        task={makeTask()}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByTestId('filter-tuning-card')).toBeInTheDocument()
    expect(screen.getByText('Filter tuning suggestion')).toBeInTheDocument()
    expect(screen.getByText('fr_01')).toBeInTheDocument()
  })

  it('shows the item summary', () => {
    render(
      <FilterTuningCard
        task={makeTask()}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByText('Fix auth token refresh')).toBeInTheDocument()
  })

  it('shows from and to action chips', () => {
    const { container } = render(
      <FilterTuningCard
        task={makeTask({ fromOutcome: 'drop', toOutcome: 'include' })}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(container.querySelector('[data-action="drop"]')).toBeInTheDocument()
    expect(container.querySelector('[data-action="include"]')).toBeInTheDocument()
  })

  it('shows the proposed prompt', () => {
    render(
      <FilterTuningCard
        task={makeTask()}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    const promptSection = screen.getByTestId('proposed-prompt')
    expect(promptSection).toHaveTextContent('Proposed prompt')
    expect(promptSection).toHaveTextContent('you corrected this')
  })

  it('calls onApply with task ID when Apply is clicked', () => {
    const onApply = vi.fn()
    render(
      <FilterTuningCard
        task={makeTask({ id: 'act_ft_test1' })}
        onApply={onApply}
        onDismiss={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(onApply).toHaveBeenCalledWith('act_ft_test1')
    expect(onApply).toHaveBeenCalledTimes(1)
  })

  it('calls onDismiss with task ID when Dismiss is clicked', () => {
    const onDismiss = vi.fn()
    render(
      <FilterTuningCard
        task={makeTask({ id: 'act_ft_test2' })}
        onApply={() => {}}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByTestId('dismiss-button'))
    expect(onDismiss).toHaveBeenCalledWith('act_ft_test2')
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('sets data-task-id attribute', () => {
    render(
      <FilterTuningCard
        task={makeTask({ id: 'act_ft_xyz99' })}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByTestId('filter-tuning-card')).toHaveAttribute(
      'data-task-id',
      'act_ft_xyz99',
    )
  })

  it('shows label action correctly with toLabel', () => {
    const { container } = render(
      <FilterTuningCard
        task={makeTask({ toOutcome: 'label', toLabel: 'spam' })}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    const labelChip = container.querySelector('[data-action="label"]')
    expect(labelChip).toBeInTheDocument()
    expect(labelChip?.textContent).toContain('label: spam')
  })
})
