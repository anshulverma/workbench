import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfidenceBar } from './ConfidenceBar'

describe('ConfidenceBar', () => {
  it('renders the percentage label', () => {
    render(<ConfidenceBar value={75} />)
    expect(screen.getByText('75%')).toBeInTheDocument()
  })

  it('sets aria-valuenow', () => {
    render(<ConfidenceBar value={42} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '42')
  })

  it('uses success color for values >= 90', () => {
    const { container } = render(<ConfidenceBar value={95} />)
    const fill = container.querySelector('.h-full')
    expect(fill).toHaveStyle({ background: 'var(--success)' })
  })

  it('uses primary color for values >= 80 and < 90', () => {
    const { container } = render(<ConfidenceBar value={85} />)
    const fill = container.querySelector('.h-full')
    expect(fill).toHaveStyle({ background: 'var(--primary)' })
  })

  it('uses brand color for values < 80', () => {
    const { container } = render(<ConfidenceBar value={60} />)
    const fill = container.querySelector('.h-full')
    expect(fill).toHaveStyle({ background: 'var(--brand)' })
  })

  it('sets fill width as percentage', () => {
    const { container } = render(<ConfidenceBar value={73} />)
    const fill = container.querySelector('.h-full')
    expect(fill).toHaveStyle({ width: '73%' })
  })
})
