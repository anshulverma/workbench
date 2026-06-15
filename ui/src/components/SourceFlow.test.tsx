import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SourceFlow } from './SourceFlow'
import type { FlowMatrix } from '@/lib/funnel-helpers'

// jsdom lacks SVG geometry methods. Patch Element.prototype so that any
// <path> created by jsdom (which is always Element in jsdom's DOM) has
// getTotalLength / getPointAtLength available.
beforeAll(() => {
  // @ts-expect-error -- jsdom polyfill
  Element.prototype.getTotalLength ??= () => 100
  // @ts-expect-error -- jsdom polyfill
  Element.prototype.getPointAtLength ??= () => ({ x: 50, y: 50 })
})

afterEach(() => {
  vi.restoreAllMocks()
})

function makeSampleMatrix(): FlowMatrix {
  return {
    sources: [
      { id: 'github', label: 'github', vol: 612 },
      { id: 'email', label: 'email', vol: 388 },
      { id: 'calendar', label: 'calendar', vol: 144 },
      { id: 'chat', label: 'chat', vol: 140 },
    ],
    outputs: [
      { id: 'action_items', label: 'Action Items', vol: 280 },
      { id: 'triage_queue', label: 'Triage Queue', vol: 410 },
      { id: 'filtered_out', label: 'Filtered Out', vol: 540 },
      { id: 'errors', label: 'Errors', vol: 54 },
    ],
    matrix: [
      [150, 230, 210, 22],
      [80, 110, 180, 18],
      [38, 50, 50, 6],
      [12, 20, 100, 8],
    ],
  }
}

function makeEmptyMatrix(): FlowMatrix {
  return {
    sources: [
      { id: 'github', label: 'github', vol: 0 },
      { id: 'email', label: 'email', vol: 0 },
    ],
    outputs: [
      { id: 'action_items', label: 'Action Items', vol: 0 },
      { id: 'triage_queue', label: 'Triage Queue', vol: 0 },
      { id: 'filtered_out', label: 'Filtered Out', vol: 0 },
      { id: 'errors', label: 'Errors', vol: 0 },
    ],
    matrix: [
      [0, 0, 0, 0],
      [0, 0, 0, 0],
    ],
  }
}

describe('SourceFlow', () => {
  describe('UI states', () => {
    it('renders loading skeleton when data is undefined', () => {
      render(<SourceFlow />)
      expect(screen.getByTestId('source-flow-loading')).toBeInTheDocument()
    })

    it('renders error card with destructive styling', () => {
      render(<SourceFlow error="Connection failed" />)
      const card = screen.getByTestId('source-flow-error')
      expect(card).toBeInTheDocument()
      expect(card.textContent).toContain('Connection failed')
    })

    it('renders empty overlay when all volumes are zero', () => {
      render(<SourceFlow data={makeEmptyMatrix()} />)
      expect(screen.getByTestId('source-flow-empty')).toBeInTheDocument()
    })

    it('renders normal state with SVG and source/output nodes', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const flow = screen.getByTestId('source-flow')
      expect(flow).toBeInTheDocument()
      // Should have the SVG with role="img"
      const svg = flow.querySelector('svg[role="img"]')
      expect(svg).toBeTruthy()
      // Source nodes present
      expect(flow.querySelector('[data-source="github"]')).toBeTruthy()
      expect(flow.querySelector('[data-source="email"]')).toBeTruthy()
      expect(flow.querySelector('[data-source="calendar"]')).toBeTruthy()
      expect(flow.querySelector('[data-source="chat"]')).toBeTruthy()
      // Output nodes present
      expect(flow.querySelector('[data-output="action_items"]')).toBeTruthy()
      expect(flow.querySelector('[data-output="triage_queue"]')).toBeTruthy()
      expect(flow.querySelector('[data-output="filtered_out"]')).toBeTruthy()
      expect(flow.querySelector('[data-output="errors"]')).toBeTruthy()
    })

    it('renders degraded state with stalled source indicator', () => {
      render(
        <SourceFlow
          data={makeSampleMatrix()}
          stalledSources={new Set(['github'])}
        />,
      )
      const flow = screen.getByTestId('source-flow')
      const githubNode = flow.querySelector('[data-source="github"]')
      expect(githubNode).toBeTruthy()
      // The stalled source should show "STALLED" label
      expect(githubNode!.textContent).toContain('stalled')
    })
  })

  describe('layout and SVG structure', () => {
    it('has viewBox 760x210', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const svg = screen.getByTestId('source-flow').querySelector('svg')
      expect(svg?.getAttribute('viewBox')).toBe('0 0 760 210')
    })

    it('contains 80 dot circles for the animation pool', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const dots = screen
        .getByTestId('source-flow')
        .querySelectorAll('[data-dot]')
      expect(dots.length).toBe(80)
    })

    it('renders the central WorkBench module with WB icon', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const img = screen.getByTestId('source-flow').querySelector('img[alt="WorkBench"]')
      expect(img).toBeTruthy()
      expect(img?.getAttribute('src')).toBe('/wb-icon.svg')
    })

    it('displays ingest and egress rates in the central module', () => {
      render(
        <SourceFlow
          data={makeSampleMatrix()}
          ingestRate={12}
          egressRate={8}
        />,
      )
      const flow = screen.getByTestId('source-flow')
      expect(flow.textContent).toContain('12')
      expect(flow.textContent).toContain('8')
      expect(flow.textContent).toContain('IN/h')
      expect(flow.textContent).toContain('OUT/h')
    })
  })

  describe('stalled sources', () => {
    it('renders stalled label for erroring sources', () => {
      render(
        <SourceFlow
          data={makeSampleMatrix()}
          stalledSources={new Set(['email'])}
        />,
      )
      const emailNode = screen
        .getByTestId('source-flow')
        .querySelector('[data-source="email"]')
      expect(emailNode!.textContent).toContain('stalled')
    })

    it('stalled source ribbons have dashed red stroke', () => {
      render(
        <SourceFlow
          data={makeSampleMatrix()}
          stalledSources={new Set(['github'])}
        />,
      )
      const svg = screen.getByTestId('source-flow').querySelector('svg')!
      // Find paths with stroke-dasharray (stalled ribbon)
      const dashedPaths = svg.querySelectorAll(
        'path[stroke-dasharray="5 3"]',
      )
      expect(dashedPaths.length).toBeGreaterThan(0)
    })

    it('active sources show per-day rate', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const githubNode = screen
        .getByTestId('source-flow')
        .querySelector('[data-source="github"]')
      // github vol=612, perDay(612) = Math.max(1, Math.round(612/14)) = 44
      expect(githubNode!.textContent).toContain('44')
      expect(githubNode!.textContent).toContain('/d')
    })
  })

  describe('prefers-reduced-motion', () => {
    it('skips rAF loop when reduced motion is preferred', () => {
      const originalMatchMedia = window.matchMedia
      const rafSpy = vi.spyOn(window, 'requestAnimationFrame')

      // Mock matchMedia to return prefers-reduced-motion: reduce
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))

      render(<SourceFlow data={makeSampleMatrix()} />)

      // With reduced motion, requestAnimationFrame should not be called
      // by the dot animation effect
      expect(rafSpy).not.toHaveBeenCalled()

      window.matchMedia = originalMatchMedia
      rafSpy.mockRestore()
    })
  })

  describe('sr-only table', () => {
    it('renders a screen-reader-only table with source data', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const table = screen.getByTestId('source-flow-sr-table')
      expect(table).toBeInTheDocument()
      expect(table.tagName).toBe('TABLE')

      // Should list all sources
      const rows = table.querySelectorAll('tbody tr')
      expect(rows.length).toBe(4)

      // Check source names are present
      expect(table.textContent).toContain('github')
      expect(table.textContent).toContain('email')
      expect(table.textContent).toContain('calendar')
      expect(table.textContent).toContain('chat')
    })

    it('marks stalled sources as stalled in the sr table', () => {
      render(
        <SourceFlow
          data={makeSampleMatrix()}
          stalledSources={new Set(['github'])}
        />,
      )
      const table = screen.getByTestId('source-flow-sr-table')
      const rows = table.querySelectorAll('tbody tr')
      // First row (github) should be stalled
      expect(rows[0].textContent).toContain('stalled')
      // Others should be active
      expect(rows[1].textContent).toContain('active')
    })

    it('includes output summary in table footer', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const table = screen.getByTestId('source-flow-sr-table')
      expect(table.textContent).toContain('Action Items: 280')
      expect(table.textContent).toContain('Triage Queue: 410')
      expect(table.textContent).toContain('Filtered Out: 540')
      expect(table.textContent).toContain('Errors: 54')
    })
  })

  describe('accessibility', () => {
    it('SVG has role="img" and aria-label', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const svg = screen.getByTestId('source-flow').querySelector('svg')
      expect(svg?.getAttribute('role')).toBe('img')
      expect(svg?.getAttribute('aria-label')).toContain('Signal flow')
    })

    it('SVG has a <title> element describing the diagram', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const title = screen
        .getByTestId('source-flow')
        .querySelector('svg > title')
      expect(title).toBeTruthy()
      expect(title!.textContent).toContain('source')
    })

    it('source and output nodes have <title> elements', () => {
      render(<SourceFlow data={makeSampleMatrix()} />)
      const flow = screen.getByTestId('source-flow')
      const titles = flow.querySelectorAll('g > title')
      // 4 sources + 4 outputs = 8 titles
      expect(titles.length).toBe(8)
    })
  })

  describe('navigation', () => {
    it('calls onNavigate when an output node is clicked', () => {
      const navigate = vi.fn()
      render(
        <SourceFlow data={makeSampleMatrix()} onNavigate={navigate} />,
      )
      const actionNode = screen
        .getByTestId('source-flow')
        .querySelector('[data-output="action_items"]')!
      fireEvent.click(actionNode)
      expect(navigate).toHaveBeenCalledWith('/actions')
    })

    it('navigates to /triage for triage_queue output', () => {
      const navigate = vi.fn()
      render(
        <SourceFlow data={makeSampleMatrix()} onNavigate={navigate} />,
      )
      const triageNode = screen
        .getByTestId('source-flow')
        .querySelector('[data-output="triage_queue"]')!
      fireEvent.click(triageNode)
      expect(navigate).toHaveBeenCalledWith('/triage')
    })
  })
})
