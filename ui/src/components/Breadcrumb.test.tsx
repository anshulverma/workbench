import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Breadcrumb } from './Breadcrumb'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Breadcrumb />
    </MemoryRouter>,
  )
}

describe('Breadcrumb', () => {
  it('is hidden at /', () => {
    const { container } = renderAt('/')
    expect(container.querySelector('button')).toBeNull()
  })

  it('shows "Overview" on non-triage pages', () => {
    renderAt('/search')
    const btn = screen.getByRole('button', { name: /back to overview/i })
    expect(btn).toBeInTheDocument()
    expect(btn.textContent).toContain('Overview')
  })

  it('shows "Triage" on /triage/* sub-routes', () => {
    renderAt('/triage/item-123')
    const btn = screen.getByRole('button', { name: /back to triage/i })
    expect(btn).toBeInTheDocument()
    expect(btn.textContent).toContain('Triage')
  })

  it('shows "Overview" on /triage (not a sub-route)', () => {
    renderAt('/triage')
    const btn = screen.getByRole('button', { name: /back to overview/i })
    expect(btn).toBeInTheDocument()
  })

  it('shows "Overview" on /settings', () => {
    renderAt('/settings')
    const btn = screen.getByRole('button', { name: /back to overview/i })
    expect(btn).toBeInTheDocument()
  })
})
