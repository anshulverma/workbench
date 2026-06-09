import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Button } from './button'

describe('Button', () => {
  it('default variant is a solid orange fill with near-black foreground', () => {
    render(<Button>Run</Button>)
    const el = screen.getByRole('button', { name: 'Run' })
    expect(el.className).toContain('bg-primary')
    expect(el.className).toContain('text-primary-foreground')
  })

  it('outline variant uses token border + mono label', () => {
    render(<Button variant="outline">Cancel</Button>)
    const el = screen.getByRole('button', { name: 'Cancel' })
    expect(el.className).toContain('border-border')
    expect(el.className).toContain('font-mono')
  })

  it('uses the orange focus ring', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button', { name: 'Go' }).className).toContain(
      'focus-visible:ring-ring',
    )
  })
})
