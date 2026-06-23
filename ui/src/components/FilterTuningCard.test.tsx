import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FilterTuningCard } from './FilterTuningCard'
import type { ServerTuningTask } from '@/hooks/useFeedback'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTask(overrides: Partial<ServerTuningTask> = {}): ServerTuningTask {
  return {
    id: 42,
    rule_id: 1,
    filter_id: 'fr_01',
    item_id: 101,
    item_summary: 'Fix auth token refresh',
    from_outcome: 'drop',
    to_outcome: 'include',
    from_label: null,
    to_label: null,
    filter_prompt: 'Drop bot-generated noise',
    proposed_prompt:
      'Drop bot-generated noise — but kept and surfaced cases like "Fix auth token refresh" (you corrected this).',
    kind: 'filter-tuning',
    correction_ids: [],
    status: 'open',
    created_at: new Date().toISOString(),
    resolved_at: null,
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

  it('marks the card highlighted only when the highlighted prop is set', () => {
    const { rerender } = render(
      <FilterTuningCard task={makeTask()} onApply={() => {}} onDismiss={() => {}} />,
    )
    expect(screen.getByTestId('filter-tuning-card')).not.toHaveAttribute(
      'data-highlighted',
      'true',
    )
    rerender(
      <FilterTuningCard
        task={makeTask()}
        onApply={() => {}}
        onDismiss={() => {}}
        highlighted
      />,
    )
    expect(screen.getByTestId('filter-tuning-card')).toHaveAttribute(
      'data-highlighted',
      'true',
    )
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
        task={makeTask({ from_outcome: 'drop', to_outcome: 'include' })}
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
        task={makeTask({ id: 99 })}
        onApply={onApply}
        onDismiss={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('apply-button'))
    expect(onApply).toHaveBeenCalledWith(99)
    expect(onApply).toHaveBeenCalledTimes(1)
  })

  it('calls onDismiss with task ID when Dismiss is clicked', () => {
    const onDismiss = vi.fn()
    render(
      <FilterTuningCard
        task={makeTask({ id: 88 })}
        onApply={() => {}}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByTestId('dismiss-button'))
    expect(onDismiss).toHaveBeenCalledWith(88)
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('sets data-task-id attribute', () => {
    render(
      <FilterTuningCard
        task={makeTask({ id: 77 })}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(screen.getByTestId('filter-tuning-card')).toHaveAttribute(
      'data-task-id',
      '77',
    )
  })

  it('shows label action correctly with to_label', () => {
    const { container } = render(
      <FilterTuningCard
        task={makeTask({ to_outcome: 'label', to_label: 'spam' })}
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    )
    const labelChip = container.querySelector('[data-action="label"]')
    expect(labelChip).toBeInTheDocument()
    expect(labelChip?.textContent).toContain('label: spam')
  })
})
