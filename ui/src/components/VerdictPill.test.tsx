import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VerdictPill } from './VerdictPill'
import type { Verdict } from '@/lib/types/funnel'

function makeVerdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    decision: 'triaged',
    rationale: 'test rationale',
    ...overrides,
  }
}

describe('VerdictPill', () => {
  it('renders "triaged" decision with success styling', () => {
    const { container } = render(<VerdictPill verdict={makeVerdict({ decision: 'triaged' })} />)
    expect(screen.getByText(/triaged/i)).toBeInTheDocument()
    expect(container.querySelector('[data-verdict="triaged"]')).toHaveStyle({
      background: 'var(--success)',
    })
  })

  it('renders "dropped" decision with destructive styling', () => {
    const { container } = render(
      <VerdictPill verdict={makeVerdict({ decision: 'dropped' })} />,
    )
    expect(screen.getByText(/dropped/i)).toBeInTheDocument()
    const el = container.querySelector('[data-verdict="dropped"]')
    expect(el).toHaveStyle({ color: '#ffb4ab' })
  })

  it('renders "queued" decision with tertiary styling', () => {
    const { container } = render(
      <VerdictPill verdict={makeVerdict({ decision: 'queued' })} />,
    )
    expect(screen.getByText(/in triage queue/i)).toBeInTheDocument()
    expect(container.querySelector('[data-verdict="queued"]')).toHaveStyle({
      background: 'var(--tertiary)',
    })
  })

  it('shows priority when present', () => {
    render(
      <VerdictPill verdict={makeVerdict({ priority: 'P1' })} />,
    )
    expect(screen.getByText(/~P1/)).toBeInTheDocument()
  })

  it('hides priority when null', () => {
    const { container } = render(
      <VerdictPill verdict={makeVerdict({ priority: undefined })} />,
    )
    expect(container.textContent).not.toContain('~')
  })

  it('shows confidence when present', () => {
    render(
      <VerdictPill verdict={makeVerdict({ confidence: 92 })} />,
    )
    expect(screen.getByText(/92%/)).toBeInTheDocument()
  })

  it('applies large variant sizing', () => {
    const { container } = render(
      <VerdictPill verdict={makeVerdict()} large />,
    )
    const el = container.querySelector('[data-verdict]')
    expect(el?.className).toContain('text-[13px]')
  })

  it('applies default sizing when large is not set', () => {
    const { container } = render(
      <VerdictPill verdict={makeVerdict()} />,
    )
    const el = container.querySelector('[data-verdict]')
    expect(el?.className).toContain('text-[11px]')
  })
})
