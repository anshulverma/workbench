import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Mono } from './Mono'

describe('Mono', () => {
  it('renders children with font-mono + tabular-nums classes', () => {
    render(<Mono>WRK-9402</Mono>)
    const el = screen.getByText('WRK-9402')
    expect(el.className).toContain('font-mono')
    expect(el.className).toContain('tabular-nums')
  })

  it('merges an extra className', () => {
    render(<Mono className="text-destructive">404</Mono>)
    expect(screen.getByText('404').className).toContain('text-destructive')
  })

  it('renders inside a span element', () => {
    render(<Mono>abc123</Mono>)
    expect(screen.getByText('abc123').tagName).toBe('SPAN')
  })
})
