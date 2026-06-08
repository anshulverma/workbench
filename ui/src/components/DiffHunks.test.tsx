import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DiffHunks, type Hunk } from './DiffHunks'

const HUNKS: Hunk[] = [
  { file: 'client.py', header: '@@ -1 +1,2 @@', code: '+added line\n-removed line\n unchanged',
    annotation: 'adds retry', rank: 1 },
  { file: 'b.py', header: '@@ -5 +5 @@', code: '+other', annotation: 'x', rank: 2 },
]

describe('DiffHunks', () => {
  it('renders one collapsible block per file and auto-expands the top hunk', () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    expect(screen.getByText('client.py')).toBeInTheDocument()
    expect(screen.getByText('b.py')).toBeInTheDocument()
    // top (rank 1) hunk auto-expanded -> its code lines are visible
    expect(screen.getByText('+added line')).toBeInTheDocument()
  })

  it('colors + and - lines via CSS classes only', () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    const added = screen.getByText('+added line')
    const removed = screen.getByText('-removed line')
    expect(added.className).toMatch(/add/)
    expect(removed.className).toMatch(/del/)
  })

  it('respects maxHunks cap', () => {
    const many: Hunk[] = Array.from({ length: 20 }, (_, i) => ({
      file: `f${i}.py`, header: '@@', code: '+x', annotation: 'a', rank: i + 1,
    }))
    render(<DiffHunks hunks={many} maxHunks={15} />)
    expect(screen.getAllByRole('button', { name: /\.py/ }).length).toBe(15)
  })

  it('expands a collapsed file on click', async () => {
    render(<DiffHunks hunks={HUNKS} maxHunks={15} />)
    // b.py (rank 2) starts collapsed
    expect(screen.queryByText('+other')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /b\.py/ }))
    expect(screen.getByText('+other')).toBeInTheDocument()
  })
})
