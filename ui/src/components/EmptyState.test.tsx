import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders the message in a mono terminal frame', () => {
    render(<EmptyState message="No cards" />)
    expect(screen.getByText('No cards')).toBeInTheDocument()
    expect(screen.getByText(/\/\/ end of feed/i)).toBeInTheDocument()
  })

  it('renders an optional cta', () => {
    render(<EmptyState message="x" cta={<button>Add</button>} />)
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
  })
})
