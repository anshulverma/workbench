import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from './tooltip'

describe('tooltip', () => {
  it('shows content on focus', async () => {
    const user = userEvent.setup()
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>Trigger</TooltipTrigger>
          <TooltipContent>Overview</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    )
    await user.tab()
    expect(await screen.findAllByText('Overview')).not.toHaveLength(0)
  })
})
