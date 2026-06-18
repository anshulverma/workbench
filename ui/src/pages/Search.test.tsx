// Search page tests — master/detail layout with contextual payload renderers,
// processing log, item actions, keyboard navigation, and WCAG compliance.

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { Search } from './Search'
import { _resetToken } from '@/lib/api'

const NOW = Date.now()
const iso = (msAgo: number) => new Date(NOW - msAgo).toISOString()
const HOUR = 3_600_000

const DIFF_ITEM = {
  id: 'D12345',
  kind: 'diff',
  path: '2.1',
  summary: 'Fix auth middleware race condition',
  source: 'phabricator',
  priority: 'P1',
  state: 'triaged',
  relevance: 92,
  tags: ['security', 'auth'],
  created_at: iso(2 * HOUR),
  llm_summary: 'This diff fixes a critical race condition in the auth middleware.',
  context: {
    type: 'diff',
    author: 'alice',
    team: 'infra',
    status: 'Needs Review',
    url: 'https://phabricator.example.com/D12345',
    hunks: [
      {
        file: 'src/auth.py',
        header: '@@ -10,5 +10,8 @@',
        rank: 1,
        code: '+import asyncio\n from fastapi import Request',
      },
    ],
  },
  stages: [
    { filterId: 'f_relevance', outcome: 'include', reason: 'High relevance', confidence: 95 },
    { filterId: 'f_noise', outcome: 'pass', reason: 'Not noise' },
  ],
  verdict: { decision: 'triaged', priority: 'P1', confidence: 92, rationale: 'Critical security fix' },
}

const EMAIL_ITEM = {
  id: 'E67890',
  kind: 'email',
  summary: 'Weekly ops report',
  source: 'email',
  priority: 'P3',
  state: 'pending_triage',
  relevance: 45,
  tags: ['ops'],
  created_at: iso(5 * HOUR),
  llm_summary: 'Standard weekly ops report, low urgency.',
  context: {
    type: 'email',
    from: 'ops@example.com',
    to: 'you@example.com',
    when: iso(5 * HOUR),
    body: 'All systems nominal.',
  },
  stages: [
    { filterId: 'f_noise', outcome: 'pass', reason: 'Matched keyword' },
  ],
  verdict: { decision: 'queued', rationale: 'Low priority ops report' },
}

const MEETING_ITEM = {
  id: 'M11111',
  kind: 'meeting',
  summary: 'Sprint retro',
  source: 'calendar',
  priority: null,
  state: 'action_item',
  relevance: 70,
  tags: ['team'],
  created_at: iso(1 * HOUR),
  llm_summary: 'Upcoming sprint retro for your team.',
  context: {
    type: 'meeting',
    when: iso(1 * HOUR),
    duration: '30m',
    location: 'Room A',
    attendees: ['alice', 'bob'],
    agenda: 'Discuss Q3 goals',
  },
  stages: [],
  verdict: { decision: 'triaged', rationale: 'Team meeting' },
}

const CHAT_ITEM = {
  id: 'C22222',
  kind: 'chat',
  summary: 'Deploy question in #eng',
  source: 'chat',
  priority: 'P2',
  state: 'triaged',
  relevance: 60,
  tags: ['deploy'],
  created_at: iso(3 * HOUR),
  llm_summary: 'Someone asked about the deploy in #eng.',
  context: {
    type: 'chat',
    channel: '#eng',
    messages: [
      { who: 'charlie', text: 'Is the deploy done?', when: iso(3 * HOUR) },
      { who: 'dana', text: 'Yes, all green', when: iso(2.5 * HOUR) },
    ],
  },
  stages: [],
  verdict: { decision: 'triaged', rationale: 'Deploy question resolved' },
}

const ALL_ITEMS = [DIFF_ITEM, EMAIL_ITEM, MEETING_ITEM, CHAT_ITEM]

function baseHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/api/funnel/items', () => HttpResponse.json(ALL_ITEMS)),
  ]
}

const server = setupServer(...baseHandlers())
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  server.resetHandlers()
  _resetToken()
})
afterAll(() => server.close())

function renderSearch() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/search']}>
        <Search />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Search page', () => {
  it('renders the loading state', () => {
    // Delay the response so loading state shows
    server.use(
      http.get('/api/funnel/items', async () => {
        await new Promise(() => {}) // never resolves
      }),
    )
    renderSearch()
    expect(screen.getByTestId('search-loading')).toBeInTheDocument()
  })

  it('renders the search page with results after loading', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Search items')).toBeInTheDocument()
    // Items appear both in the result list and possibly in the detail panel,
    // so use getAllByText for the first (selected) item.
    expect(screen.getAllByText('Fix auth middleware race condition').length).toBeGreaterThanOrEqual(1)
    const listbox = screen.getByRole('listbox')
    expect(within(listbox).getByText('Weekly ops report')).toBeInTheDocument()
    expect(within(listbox).getByText('Sprint retro')).toBeInTheDocument()
    expect(within(listbox).getByText('Deploy question in #eng')).toBeInTheDocument()
  })

  it('links a search result to its item lineage page', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const link = await screen.findByRole('link', { name: '#2.1' })
    expect(link).toHaveAttribute('href', '/items/2.1')
  })

  it('auto-focuses the search input on mount', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    // The auto-focus useEffect fires after the loading skeleton is replaced
    // by the real UI; wait for focus to propagate.
    await waitFor(() => {
      expect(screen.getByLabelText('Search items')).toHaveFocus()
    })
  })

  it('shows the detail panel for the first item by default', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    // The first item (DIFF_ITEM) should be selected and its detail shown
    expect(screen.getByText('Why this matters to you')).toBeInTheDocument()
    expect(
      screen.getByText('This diff fixes a critical race condition in the auth middleware.'),
    ).toBeInTheDocument()
  })

  it('shows empty placeholder when no item is selected and list is empty', async () => {
    server.use(http.get('/api/funnel/items', () => HttpResponse.json([])))
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    expect(
      screen.getByText('// select an item to inspect its full processing log'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('// No items match your search'),
    ).toBeInTheDocument()
  })

  it('filters results by kind buttons', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()

    // Initially all 4 items are in the listbox
    const listbox = screen.getByRole('listbox')
    expect(within(listbox).getAllByRole('option')).toHaveLength(4)

    // Click "Email" filter
    await user.click(screen.getByRole('button', { name: 'Email' }))

    // Only email item remains
    await waitFor(() => {
      expect(within(listbox).getAllByRole('option')).toHaveLength(1)
    })
    expect(within(listbox).getByText('Weekly ops report')).toBeInTheDocument()
    expect(within(listbox).queryByText('Fix auth middleware race condition')).not.toBeInTheDocument()
  })

  it('clears search with the clear button', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    const input = screen.getByLabelText('Search items')

    // Type a single character so clear button appears
    await user.type(input, 'x')
    await waitFor(() => {
      expect(input).toHaveValue('x')
    })

    const clearBtn = screen.getByLabelText('Clear')
    await user.click(clearBtn)
    expect(input).toHaveValue('')
  })

  it('renders the unauthorized state on 401', async () => {
    server.use(
      http.get('/api/auth/token', () =>
        HttpResponse.json({ error: 'no' }, { status: 401 }),
      ),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-unauthorized')).toBeInTheDocument()
    })
    expect(screen.getByText(/token unavailable/)).toBeInTheDocument()
  })

  it('renders the error state with request ID', async () => {
    server.use(
      http.get('/api/funnel/items', () =>
        HttpResponse.json(
          { detail: 'Internal Server Error' },
          {
            status: 500,
            headers: { 'X-Request-ID': 'req_abc123' },
          },
        ),
      ),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-error')).toBeInTheDocument()
    })
    expect(screen.getByText(/Request ID: req_abc123/)).toBeInTheDocument()
  })

  it('renders diff contextual payload in detail panel', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    // The first item is the diff; its context should show
    expect(screen.getByText('View in Phabricator')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('infra')).toBeInTheDocument()
    expect(screen.getByText('Needs Review')).toBeInTheDocument()
  })

  it('switches to email context when email item is clicked', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()

    // Click the email result
    const listbox = screen.getByRole('listbox')
    const emailOption = within(listbox).getByText('Weekly ops report')
    await user.click(emailOption)

    // Should now show email context
    await waitFor(() => {
      expect(screen.getByText('ops@example.com')).toBeInTheDocument()
    })
    expect(screen.getByText('you@example.com')).toBeInTheDocument()
    expect(screen.getByText('All systems nominal.')).toBeInTheDocument()
  })

  it('shows meeting context with agenda', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()

    const listbox = screen.getByRole('listbox')
    const meetingOption = within(listbox).getByText('Sprint retro')
    await user.click(meetingOption)

    await waitFor(() => {
      expect(screen.getByText('Discuss Q3 goals')).toBeInTheDocument()
    })
    expect(screen.getByText('Room A')).toBeInTheDocument()
  })

  it('shows chat context with threaded messages', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()

    const listbox = screen.getByRole('listbox')
    const chatOption = within(listbox).getByText('Deploy question in #eng')
    await user.click(chatOption)

    await waitFor(() => {
      expect(screen.getByText('#eng')).toBeInTheDocument()
    })
    expect(screen.getByText('Is the deploy done?')).toBeInTheDocument()
    expect(screen.getByText('Yes, all green')).toBeInTheDocument()
  })

  it('uses WCAG role=listbox with role=option rows', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const listbox = screen.getByRole('listbox')
    expect(listbox).toBeInTheDocument()
    const options = within(listbox).getAllByRole('option')
    expect(options.length).toBe(4)
    // First option should be selected
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('keyboard navigates with ArrowDown/ArrowUp', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    const listbox = screen.getByRole('listbox')

    // Focus the listbox
    listbox.focus()

    // First item selected by default
    const options = within(listbox).getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')

    // ArrowDown moves to second item
    await user.keyboard('{ArrowDown}')
    await waitFor(() => {
      const updated = within(listbox).getAllByRole('option')
      expect(updated[1]).toHaveAttribute('aria-selected', 'true')
    })

    // ArrowUp moves back to first
    await user.keyboard('{ArrowUp}')
    await waitFor(() => {
      const updated = within(listbox).getAllByRole('option')
      expect(updated[0]).toHaveAttribute('aria-selected', 'true')
    })
  })

  it('Escape clears search and focuses input', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    const input = screen.getByLabelText('Search items')
    await user.type(input, 'z')
    await waitFor(() => {
      expect(input).toHaveValue('z')
    })

    const listbox = screen.getByRole('listbox')
    listbox.focus()
    await user.keyboard('{Escape}')

    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
  })

  it('shows processing log with funnel stages', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    // The diff item has 2 stages
    const stages = screen.getAllByTestId('funnel-stage')
    expect(stages.length).toBeGreaterThanOrEqual(2)
  })

  it('shows verdict pill in the detail panel', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    expect(screen.getByText('Current verdict')).toBeInTheDocument()
    expect(screen.getByText('Critical security fix')).toBeInTheDocument()
  })

  it('shows tags in the detail header', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    expect(screen.getByText('#security')).toBeInTheDocument()
    expect(screen.getByText('#auth')).toBeInTheDocument()
  })

  it('fires archive mutation on Mark done', async () => {
    let archiveCalled = false
    server.use(
      http.post('/api/items/:id/archive', () => {
        archiveCalled = true
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Mark done' }))
    await waitFor(() => {
      expect(archiveCalled).toBe(true)
    })
  })

  it('fires snooze mutation on Snooze 4h', async () => {
    let snoozeCalled = false
    server.use(
      http.post('/api/items/:id/snooze', () => {
        snoozeCalled = true
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Snooze 4h' }))
    await waitFor(() => {
      expect(snoozeCalled).toBe(true)
    })
  })

  it('fires archive mutation on Archive', async () => {
    let archiveCalled = false
    server.use(
      http.post('/api/items/:id/archive', () => {
        archiveCalled = true
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Archive' }))
    await waitFor(() => {
      expect(archiveCalled).toBe(true)
    })
  })

  it('fires delete action and shows toast', async () => {
    server.use(
      http.post('/api/items/:id/archive', () =>
        HttpResponse.json({ status: 'ok' }),
      ),
    )
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => {
      expect(screen.getByText(/Deleted D12345/)).toBeInTheDocument()
    })
  })

  it('shows result count in the search bar', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    // 4 items total
    expect(screen.getByText('4')).toBeInTheDocument()
  })

  it('shows kind filter buttons', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Diffs' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Email' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Meetings' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chat' })).toBeInTheDocument()
  })

  it('priority select fires onAction with the chosen value', async () => {
    renderSearch()
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })
    const user = userEvent.setup()
    const select = screen.getByLabelText('Set priority')
    await user.selectOptions(select, 'P0')
    await waitFor(() => {
      expect(screen.getByText(/Set D12345/)).toBeInTheDocument()
    })
  })
})
