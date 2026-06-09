import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LogStream } from './LogStream'

describe('LogStream', () => {
  it('renders mono log lines', () => {
    render(<LogStream lines={[{ id: '1', text: 'github poll ok' }]} />)
    const el = screen.getByText('github poll ok')
    expect(el.closest('[data-logstream]')).toBeTruthy()
  })

  it('renders an empty terminal state', () => {
    render(<LogStream lines={[]} />)
    expect(screen.getByText(/no activity/i)).toBeInTheDocument()
  })

  it('exposes a polite live log region', () => {
    render(<LogStream lines={[{ id: '1', text: 'x' }]} />)
    expect(screen.getByRole('log')).toHaveAttribute('aria-live', 'polite')
  })
})
