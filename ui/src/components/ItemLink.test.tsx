import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useSearchParams } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ItemLink } from './ItemLink'

function ParamProbe() {
  const [p] = useSearchParams()
  return <span data-testid="param">{p.get('item') ?? ''}</span>
}

describe('ItemLink', () => {
  it('sets ?item=<id> on click without navigating away', async () => {
    render(
      <MemoryRouter initialEntries={['/actions']}>
        <ItemLink id={42}>#42</ItemLink>
        <ParamProbe />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('#42'))
    await waitFor(() => expect(screen.getByTestId('param').textContent).toBe('42'))
  })
})
