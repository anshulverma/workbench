import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from './badge'

describe('Badge', () => {
  it('is mono by default', () => {
    render(<Badge>github</Badge>)
    expect(screen.getByText('github').className).toContain('font-mono')
  })

  it('renders a p0 priority variant (tinted bg + border)', () => {
    render(<Badge variant="p0">P0</Badge>)
    const el = screen.getByText('P0')
    expect(el.className).toMatch(/border/)
  })

  it('supports p1/p2/p3 variants', () => {
    for (const v of ['p1', 'p2', 'p3'] as const) {
      const { unmount } = render(<Badge variant={v}>{v}</Badge>)
      expect(screen.getByText(v)).toBeInTheDocument()
      unmount()
    }
  })
})
