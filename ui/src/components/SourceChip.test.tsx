import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourceChip } from './SourceChip'

describe('SourceChip', () => {
  it('renders the source name', () => {
    render(<SourceChip name="github" />)
    expect(screen.getByText('github')).toBeInTheDocument()
  })

  it.each(['github', 'email', 'calendar', 'chat'])(
    'renders icon for known source "%s"',
    (source) => {
      const { container } = render(<SourceChip name={source} />)
      // lucide renders SVGs
      expect(container.querySelector('svg')).toBeTruthy()
    },
  )

  it('uses Database fallback icon for unknown sources', () => {
    const { container } = render(<SourceChip name="unknown-source" />)
    // should still render an SVG (Database icon)
    expect(container.querySelector('svg')).toBeTruthy()
    expect(screen.getByText('unknown-source')).toBeInTheDocument()
  })
})
