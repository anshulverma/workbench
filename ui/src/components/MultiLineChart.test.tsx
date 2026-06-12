import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MultiLineChart, type ChartSeries } from './MultiLineChart'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SERIES: ChartSeries[] = [
  { name: 'Ingested', color: '#ff6a2b', data: [10, 20, 15, 30, 25] },
  { name: 'Triaged', color: '#71d2ff', data: [5, 12, 8, 20, 18] },
]

const X_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MultiLineChart', () => {
  it('renders the chart container', () => {
    render(<MultiLineChart series={SERIES} />)
    expect(screen.getByTestId('multi-line-chart')).toBeInTheDocument()
  })

  it('renders SVG with correct number of series paths', () => {
    render(<MultiLineChart series={SERIES} />)
    const paths = screen.getAllByTestId('series-path')
    expect(paths).toHaveLength(2)
  })

  it('renders y-axis labels', () => {
    render(<MultiLineChart series={SERIES} />)
    const yLabels = screen.getAllByTestId('y-label')
    expect(yLabels.length).toBe(3) // 0, mid, max
    // Ticks array is [0, mid, max] so labels render in that order
    const labelTexts = yLabels.map((el) => el.textContent)
    expect(labelTexts).toContain('0')
    expect(labelTexts).toContain('30')
  })

  it('renders legend with series names', () => {
    render(<MultiLineChart series={SERIES} />)
    const legend = screen.getByTestId('chart-legend')
    expect(legend).toHaveTextContent('Ingested')
    expect(legend).toHaveTextContent('Triaged')
  })

  it('renders x-axis labels when provided', () => {
    render(<MultiLineChart series={SERIES} xLabels={X_LABELS} />)
    expect(screen.getByTestId('x-axis-labels')).toBeInTheDocument()
    // At least first and last should show
    expect(screen.getByText('Mon')).toBeInTheDocument()
    expect(screen.getByText('Fri')).toBeInTheDocument()
  })

  it('does not render x-axis labels when not provided', () => {
    render(<MultiLineChart series={SERIES} />)
    expect(screen.queryByTestId('x-axis-labels')).not.toBeInTheDocument()
  })

  it('shows tooltip on hover', () => {
    render(<MultiLineChart series={SERIES} xLabels={X_LABELS} />)
    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()

    // Simulate mouse move over the hover capture area
    const hoverCapture = screen.getByTestId('hover-capture')
    // We need to provide clientX within the bounds; mock bounding rect
    Object.defineProperty(hoverCapture, 'getBoundingClientRect', {
      value: () => ({ left: 0, width: 320, top: 0, height: 132, right: 320, bottom: 132 }),
    })
    fireEvent.mouseMove(hoverCapture, { clientX: 160 })

    expect(screen.getByTestId('chart-tooltip')).toBeInTheDocument()
  })

  it('hides tooltip on mouse leave', () => {
    render(<MultiLineChart series={SERIES} xLabels={X_LABELS} />)
    const hoverCapture = screen.getByTestId('hover-capture')
    Object.defineProperty(hoverCapture, 'getBoundingClientRect', {
      value: () => ({ left: 0, width: 320, top: 0, height: 132, right: 320, bottom: 132 }),
    })

    fireEvent.mouseMove(hoverCapture, { clientX: 160 })
    expect(screen.getByTestId('chart-tooltip')).toBeInTheDocument()

    fireEvent.mouseLeave(hoverCapture)
    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()
  })

  it('shows hover dots when hovering', () => {
    render(<MultiLineChart series={SERIES} />)
    const hoverCapture = screen.getByTestId('hover-capture')
    Object.defineProperty(hoverCapture, 'getBoundingClientRect', {
      value: () => ({ left: 0, width: 320, top: 0, height: 132, right: 320, bottom: 132 }),
    })

    fireEvent.mouseMove(hoverCapture, { clientX: 160 })
    const dots = screen.getAllByTestId('hover-dot')
    expect(dots).toHaveLength(SERIES.length)
  })

  it('uses custom height when provided', () => {
    render(<MultiLineChart series={SERIES} height={200} />)
    const svg = screen.getByTestId('chart-svg')
    expect(svg.getAttribute('height')).toBe('200')
  })

  it('handles single data point', () => {
    const single: ChartSeries[] = [
      { name: 'Test', color: '#ff0000', data: [42] },
    ]
    render(<MultiLineChart series={single} />)
    expect(screen.getByTestId('chart-svg')).toBeInTheDocument()
    expect(screen.getAllByTestId('series-path')).toHaveLength(1)
  })

  it('handles empty series', () => {
    render(<MultiLineChart series={[]} />)
    expect(screen.getByTestId('multi-line-chart')).toBeInTheDocument()
  })
})
