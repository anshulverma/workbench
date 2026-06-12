import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ActionChip } from './ActionChip'
import type { StageOutcome } from '@/lib/types/funnel'
import { STAGE_META } from '@/lib/funnel-constants'

describe('ActionChip', () => {
  const outcomes: StageOutcome[] = [
    'context',
    'drop',
    'include',
    'label',
    'loopback',
    'pass',
    'skip',
  ]

  it.each(outcomes)('renders "%s" action with correct label', (action) => {
    const { container } = render(<ActionChip action={action} />)
    const el = container.querySelector(`[data-action="${action}"]`)!
    const text = el.textContent ?? ''
    if (action === 'label') {
      expect(text).toContain('label:')
    } else {
      expect(text).toContain(STAGE_META[action].label)
    }
  })

  it('renders label text for "label" action', () => {
    render(<ActionChip action="label" label="spam" />)
    expect(screen.getByText(/label: spam/i)).toBeInTheDocument()
  })

  it('displays confidence percentage when provided', () => {
    render(<ActionChip action="drop" confidence={87} />)
    expect(screen.getByText(/87%/)).toBeInTheDocument()
  })

  it('omits confidence when not provided', () => {
    const { container } = render(<ActionChip action="include" />)
    expect(container.textContent).not.toContain('%')
  })

  it('sets data-action attribute', () => {
    const { container } = render(<ActionChip action="pass" />)
    expect(container.querySelector('[data-action="pass"]')).toBeTruthy()
  })

  it('applies dashed border for skip action', () => {
    const { container } = render(<ActionChip action="skip" />)
    const el = container.querySelector('[data-action="skip"]')
    expect(el?.className).toContain('border-dashed')
  })

  it('applies small sizing', () => {
    const { container } = render(<ActionChip action="drop" small />)
    const el = container.querySelector('[data-action="drop"]')
    expect(el?.className).toContain('text-[10px]')
  })
})
