import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LiveTail, type TailEntry } from './LiveTail'

function makeTailEntry(overrides: Partial<TailEntry> & { key: string }): TailEntry {
  return {
    key: overrides.key,
    timestamp: overrides.timestamp ?? Date.now(),
    itemId: overrides.itemId ?? 'it_abc12',
    source: overrides.source ?? 'github',
    funnelStage: overrides.funnelStage ?? 'f_priority · auto-include',
    outcome: overrides.outcome ?? 'include',
    confidence: overrides.confidence,
    label: overrides.label,
    summary: overrides.summary,
  }
}

function makeEntries(count: number): TailEntry[] {
  return Array.from({ length: count }, (_, i) =>
    makeTailEntry({
      key: `row-${i}`,
      itemId: `it_${i}`,
      timestamp: Date.now() - (count - i) * 1000,
    }),
  )
}

describe('LiveTail', () => {
  it('renders all 5 column headers', () => {
    render(<LiveTail entries={[]} />)
    const headers = screen.getAllByRole('columnheader')
    expect(headers).toHaveLength(5)
    expect(headers.map((h) => h.textContent)).toEqual([
      'Time',
      'Item',
      'Source',
      'Funnel stage',
      'Status',
    ])
  })

  it('caps rows at 60', () => {
    const entries = makeEntries(80)
    const { container } = render(<LiveTail entries={entries} />)
    // Each entry renders as a <button> row inside the scroll area
    const rows = container.querySelectorAll('[data-testid="live-tail"] button[title]')
    expect(rows.length).toBe(60)
  })

  it('applies wb-tail-new class to the newest row only', () => {
    const entries = makeEntries(5)
    const { container } = render(<LiveTail entries={entries} />)
    const rows = container.querySelectorAll('[data-testid="live-tail"] button[title]')
    // Only the last row should have wb-tail-new
    const withFlash = Array.from(rows).filter((r) => r.classList.contains('wb-tail-new'))
    expect(withFlash).toHaveLength(1)
    expect(withFlash[0]).toBe(rows[rows.length - 1])
  })

  it('fires onOpenItem with itemId when a row is clicked', () => {
    const onOpenItem = vi.fn()
    const entries = [makeTailEntry({ key: 'r1', itemId: 'it_clicked' })]
    render(<LiveTail entries={entries} onOpenItem={onOpenItem} />)
    const row = screen.getByTitle('Open it_clicked')
    fireEvent.click(row)
    expect(onOpenItem).toHaveBeenCalledTimes(1)
    expect(onOpenItem).toHaveBeenCalledWith('it_clicked')
  })

  it('toggles between live and paused via the toggle button', () => {
    const onToggle = vi.fn()
    const { rerender } = render(
      <LiveTail entries={[]} live={true} onToggleLive={onToggle} />,
    )
    const toggle = screen.getByTestId('live-toggle')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle.textContent).toContain('live')

    fireEvent.click(toggle)
    expect(onToggle).toHaveBeenCalledTimes(1)

    // Re-render in paused state
    rerender(<LiveTail entries={[]} live={false} onToggleLive={onToggle} />)
    const togglePaused = screen.getByTestId('live-toggle')
    expect(togglePaused).toHaveAttribute('aria-pressed', 'false')
    expect(togglePaused.textContent).toContain('paused')
  })

  it('shows empty state when there are no entries and live', () => {
    render(<LiveTail entries={[]} live={true} />)
    expect(screen.getByText('Waiting for events...')).toBeInTheDocument()
  })

  it('shows paused empty state when not live', () => {
    render(<LiveTail entries={[]} live={false} />)
    expect(screen.getByText(/tail paused/)).toBeInTheDocument()
  })

  it('renders error state when error prop is set', () => {
    render(<LiveTail entries={[]} error="Connection lost" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Connection lost')
  })

  it('displays entry count in footer', () => {
    const entries = makeEntries(12)
    render(<LiveTail entries={entries} />)
    expect(screen.getByText('12 / 60')).toBeInTheDocument()
  })
})
