import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { cloneElement, isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { Sparkline } from './Sparkline'

// Recharts' ResponsiveContainer measures its parent via ResizeObserver, which
// jsdom reports as 0x0 (so the chart SVG never paints). Mock it to hand the
// chart child a concrete width/height so the area chart renders deterministically.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) =>
      isValidElement(children)
        ? cloneElement(children as ReactElement, {
            width: 200,
            height: 32,
          } as Record<string, unknown>)
        : children,
  }
})

describe('Sparkline', () => {
  it('renders an em-dash placeholder when empty', () => {
    render(<Sparkline data={[]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders an svg region for multi-point data', () => {
    const { container } = render(
      <Sparkline data={[{ count: 1 }, { count: 5 }, { count: 3 }]} />,
    )
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('renders a single dot for a single data point', () => {
    const { container } = render(<Sparkline data={[{ count: 4 }]} />)
    expect(container.querySelector('[data-sparkline-dot]')).toBeTruthy()
  })
})
