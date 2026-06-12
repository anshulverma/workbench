// AppSidebar tests (V3 shell restructure, Slice 7).
//
// Asserts the nav rail renders 7 items in the correct order, with Search at
// position 2, and that the removed items (Sources, Messenger) are absent.

import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppSidebar } from './AppSidebar'

function renderSidebar(initial = '/') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AppSidebar />
    </MemoryRouter>,
  )
}

describe('AppSidebar', () => {
  it('renders a Primary navigation landmark', () => {
    renderSidebar()
    expect(
      screen.getByRole('navigation', { name: /primary/i }),
    ).toBeInTheDocument()
  })

  it('renders exactly 7 nav items', () => {
    renderSidebar()
    const nav = screen.getByRole('navigation', { name: /primary/i })
    const items = within(nav).getAllByRole('listitem')
    expect(items).toHaveLength(7)
  })

  it('has Search at position 2 (index 1)', () => {
    renderSidebar()
    const nav = screen.getByRole('navigation', { name: /primary/i })
    const items = within(nav).getAllByRole('listitem')
    const secondLink = within(items[1]).getByRole('link')
    expect(secondLink).toHaveAttribute('aria-label', 'Search')
  })

  it('renders nav items in the correct order', () => {
    renderSidebar()
    const nav = screen.getByRole('navigation', { name: /primary/i })
    const items = within(nav).getAllByRole('listitem')
    const labels = items.map(
      (li) => within(li).getByRole('link').getAttribute('aria-label'),
    )
    expect(labels).toEqual([
      'Overview',
      'Search',
      'Triage',
      'Action Items',
      'Ingestion',
      'Knowledge',
      'Settings',
    ])
  })

  it('does NOT include Sources', () => {
    renderSidebar()
    expect(
      screen.queryByRole('link', { name: 'Sources' }),
    ).not.toBeInTheDocument()
  })

  it('does NOT include Messenger', () => {
    renderSidebar()
    expect(
      screen.queryByRole('link', { name: 'Messenger' }),
    ).not.toBeInTheDocument()
  })

  it('renders a logo link to home', () => {
    renderSidebar()
    expect(
      screen.getByRole('link', { name: /workbench home/i }),
    ).toHaveAttribute('href', '/')
  })

  it('marks the active route with aria-current="page"', () => {
    renderSidebar('/triage')
    const triageLink = screen.getByRole('link', { name: 'Triage' })
    expect(triageLink).toHaveAttribute('aria-current', 'page')
  })
})
