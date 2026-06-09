import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatCard } from './StatCard'

describe('StatCard', () => {
  it('renders an uppercase mono label and a mono value', () => {
    render(<StatCard label="Pending Triage" value={42} />)
    expect(screen.getByText('42').className).toContain('font-mono')
    expect(screen.getByText('Pending Triage').className).toContain('uppercase')
  })

  it('applies danger styling', () => {
    render(<StatCard label="Dead Letters" value={3} danger />)
    expect(screen.getByText('3').className).toContain('text-destructive')
  })

  it('renders an optional delta and sub slot', () => {
    render(
      <StatCard label="Throughput" value={7} delta="+2" sub={<span>spark</span>} />,
    )
    expect(screen.getByText('+2')).toBeInTheDocument()
    expect(screen.getByText('spark')).toBeInTheDocument()
  })
})
