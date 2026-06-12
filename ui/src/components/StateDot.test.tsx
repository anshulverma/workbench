import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StateDot } from './StateDot'
import type { ItemState } from '@/lib/types/search'

describe('StateDot', () => {
  const states: Array<{ state: ItemState; label: string; color: string }> = [
    { state: 'triaged', label: 'triaged', color: 'var(--success)' },
    { state: 'pending_triage', label: 'in triage queue', color: 'var(--tertiary)' },
    { state: 'action_item', label: 'action item', color: 'var(--primary)' },
    { state: 'dropped', label: 'dropped', color: 'var(--muted-foreground)' },
    { state: 'archived', label: 'archived', color: 'var(--muted-foreground)' },
  ]

  it.each(states)(
    'renders "$state" with label "$label"',
    ({ state, label }) => {
      render(<StateDot state={state} />)
      expect(screen.getByText(label)).toBeInTheDocument()
    },
  )

  it.each(states)(
    'renders "$state" dot with correct color',
    ({ state, color }) => {
      const { container } = render(<StateDot state={state} />)
      const dot = container.querySelector('[aria-hidden="true"]')
      expect(dot).toHaveStyle({ background: color })
    },
  )

  it('sets data-state attribute', () => {
    const { container } = render(<StateDot state="action_item" />)
    expect(container.querySelector('[data-state="action_item"]')).toBeTruthy()
  })
})
