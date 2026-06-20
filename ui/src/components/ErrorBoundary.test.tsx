import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'
import * as reporter from '@/lib/error-reporter'

function Boom(): never {
  throw new Error('render-fail')
}

beforeEach(() => {
  // suppress React's error console for this intentional throw
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(reporter, 'reportClientError').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

it('reports react render errors and shows fallback', () => {
  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  )
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(reporter.reportClientError).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'react', level: 'error', message: 'render-fail' }),
  )
})
