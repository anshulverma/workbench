import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Portal } from './Portal'

describe('Portal', () => {
  it('renders children into document.body', () => {
    const { unmount } = render(
      <Portal>
        <div data-testid="portal-child">hello from portal</div>
      </Portal>,
    )
    const child = screen.getByTestId('portal-child')
    expect(child).toBeInTheDocument()
    // The portal child should be a direct child of document.body,
    // not inside the render container
    expect(child.closest('body')).toBe(document.body)
    unmount()
  })

  it('cleans up portal content on unmount', () => {
    const { unmount } = render(
      <Portal>
        <span data-testid="ephemeral">gone soon</span>
      </Portal>,
    )
    expect(screen.getByTestId('ephemeral')).toBeInTheDocument()
    unmount()
    expect(screen.queryByTestId('ephemeral')).not.toBeInTheDocument()
  })
})
