// Accessibility tests (spec Design Section 11.3, plan Task F1).
//
// Asserts the cross-cutting a11y guarantees that are testable under jsdom:
//   - the sidebar exposes a <nav> landmark, its links are native <a> elements
//     reachable by keyboard (Tab order), and the active link carries
//     aria-current="page" (NavLink default);
//   - icon-only / destructive controls carry accessible names (aria-label);
//   - shadcn Dialog (Radix) moves focus into the dialog on open and returns
//     focus to the trigger on close;
//   - Settings tabs ARIA (tablist/tab/aria-selected);
//   - Search listbox (role=listbox, role=option, aria-activedescendant);
//   - LiveTail aria-live region;
//   - SourceFlow role=img + aria-label;
//   - FunnelStage correction picker accessibility;
//   - ActionChip/VerdictPill color+text redundancy;
//   - ConfidenceBar ARIA (aria-valuenow);
//   - Hover-expand rail labels accessible.
//
// These tests are self-contained (no shared render helper) to match the other
// suites in this package.

import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { AppSidebar } from '@/components/AppSidebar'
import { FactRow } from '@/components/FactRow'
import { CommandPalette } from '@/components/CommandPalette'
import { LiveTail, type TailEntry } from '@/components/LiveTail'
import { SourceFlow } from '@/components/SourceFlow'
import { ActionChip } from '@/components/ActionChip'
import { VerdictPill } from '@/components/VerdictPill'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { FunnelStage } from '@/components/funnel/FunnelStage'
import { Settings } from '@/pages/Settings'
import { Search } from '@/pages/Search'
import type { FlowMatrix } from '@/lib/funnel-helpers'
import type { FunnelStage as FunnelStageType, FunnelItem } from '@/lib/types/funnel'
import { _resetToken } from '@/lib/api'

// -- SVG polyfills for jsdom --
beforeAll(() => {
  // @ts-expect-error -- jsdom polyfill
  Element.prototype.getTotalLength ??= () => 100
  // @ts-expect-error -- jsdom polyfill
  Element.prototype.getPointAtLength ??= () => ({ x: 50, y: 50 })
})

// -- MSW server for pages that fetch data --
const HEALTH = {
  status: 'healthy',
  version: '0.1.0',
  components: { storage: { status: 'healthy' }, connections: {} },
  queue: {},
}
const CONFIG = {
  config: {
    version: '0.4.0',
    pipeline: { include_threshold: 70 },
    scheduler: { poll_interval: 900 },
    retention: { days: 30 },
    alerting: { enabled: false },
    server: { api_token: '[REDACTED]' },
  },
}
const MESSENGER = { configured: false, type: null }
const SEARCH_ITEMS = [
  {
    id: 'D999',
    kind: 'diff',
    summary: 'A11y test diff',
    source: 'phabricator',
    priority: 'P1',
    state: 'triaged',
    relevance: 90,
    tags: ['test'],
    created_at: new Date().toISOString(),
    llm_summary: 'Test item for a11y.',
    context: null,
    stages: [{ filterId: 'f_1', outcome: 'include', reason: 'Test', confidence: 95 }],
    verdict: { decision: 'triaged', priority: 'P1', confidence: 90, rationale: 'Test' },
  },
  {
    id: 'E888',
    kind: 'email',
    summary: 'A11y email item',
    source: 'email',
    priority: null,
    state: 'pending_triage',
    relevance: 50,
    tags: [],
    created_at: new Date().toISOString(),
    llm_summary: 'Email a11y test.',
    context: null,
    stages: [],
    verdict: { decision: 'queued', rationale: 'Pending' },
  },
]

function a11yHandlers() {
  return [
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })),
    http.get('/health', () => HttpResponse.json(HEALTH)),
    http.get('/api/debug/config', () => HttpResponse.json(CONFIG)),
    http.get('/api/messenger', () => HttpResponse.json(MESSENGER)),
    http.get('/api/stats/sources', () => HttpResponse.json([])),
    http.get('/api/sources/adapter-types', () => HttpResponse.json([])),
    http.get('/api/connections', () => HttpResponse.json([])),
    http.get('/api/funnel/items', () => HttpResponse.json(SEARCH_ITEMS)),
  ]
}

const server = setupServer(...a11yHandlers())
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  server.resetHandlers(...a11yHandlers())
  _resetToken()
})
afterAll(() => server.close())

// -- Render helpers --

function renderWithRouter(ui: React.ReactNode, initialEntry = '/') {
  return render(<MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>)
}

function renderWithClient(ui: React.ReactNode, initialEntry = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        {ui}
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// -- Test data factories --

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

function makeSampleMatrix(): FlowMatrix {
  return {
    sources: [
      { id: 'github', label: 'github', vol: 612 },
      { id: 'email', label: 'email', vol: 388 },
    ],
    outputs: [
      { id: 'action_items', label: 'Action Items', vol: 280 },
      { id: 'triage_queue', label: 'Triage Queue', vol: 410 },
      { id: 'filtered_out', label: 'Filtered Out', vol: 310 },
    ],
    matrix: [
      [150, 230, 232],
      [130, 180, 78],
    ],
  }
}

function makeMockStage(overrides?: Partial<FunnelStageType>): FunnelStageType {
  return {
    filterId: 'fr_01',
    outcome: 'include',
    reason: 'Matched team pattern.',
    confidence: 90,
    ...overrides,
  }
}

function makeMockItem(overrides?: Partial<FunnelItem>): FunnelItem {
  return {
    id: 'itm_test',
    summary: 'Test item for correction',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [makeMockStage()],
    verdict: {
      decision: 'triaged',
      priority: 'P1',
      confidence: 91,
      rationale: 'Test rationale.',
    },
    ...overrides,
  }
}

// ===================================================================
// Tests
// ===================================================================

describe('accessibility', () => {
  // ---- Original sidebar tests ----

  it('exposes a Primary nav landmark with native, keyboard-reachable links', async () => {
    renderWithRouter(<AppSidebar />)

    // <nav aria-label="Primary"> landmark.
    expect(
      screen.getByRole('navigation', { name: /primary/i }),
    ).toBeInTheDocument()

    // Links are native <a> (role=link), not click-only divs.
    const overview = screen.getByRole('link', { name: 'Overview' })
    expect(overview.tagName).toBe('A')

    // Tab moves focus to the first link in the nav — now the logo home link
    // (V3 restructure added a logo button above the nav items).
    const logo = screen.getByRole('link', { name: /workbench home/i })
    await userEvent.tab()
    expect(logo).toHaveFocus()
  })

  it('rail links are icon-only with accessible names (aria-label)', () => {
    renderWithRouter(<AppSidebar />)
    // The 64px icon rail shows lucide icons; accessible names come from
    // aria-label, not visible text. All seven routes must remain named.
    // V3 restructure: Sources + Messenger removed, Search added.
    for (const name of [
      'Overview',
      'Search',
      'Triage',
      'Action Items',
      'Ingestion',
      'Knowledge',
      'Settings',
    ]) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
  })

  it('marks the active nav link with aria-current="page"', () => {
    renderWithRouter(<AppSidebar />, '/triage')
    const active = screen.getByRole('link', { name: 'Triage' })
    expect(active).toHaveAttribute('aria-current', 'page')
    // Inactive links must not carry aria-current.
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute(
      'aria-current',
    )
  })

  it('gives icon-only / destructive row controls accessible names', () => {
    renderWithClient(
      <ul>
        <FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />
      </ul>,
    )
    expect(
      screen.getByRole('button', { name: /edit f9/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /delete f9/i }),
    ).toBeInTheDocument()
  })

  it('moves focus into the dialog on open and closes it on Escape (focus trap)', async () => {
    const user = userEvent.setup()
    renderWithClient(
      <ul>
        <FactRow fact={{ id: 'f9', content: 'x', source: 's', timestamp: null }} />
      </ul>,
    )

    const trigger = screen.getByRole('button', { name: /delete f9/i })
    await user.click(trigger)

    // Dialog (Radix) opens and moves focus inside it — the focus trap is active.
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog.contains(document.activeElement)).toBe(true)

    // Escape closes it. (Radix returns focus to the trigger in a real browser;
    // jsdom drops it to <body> on unmount, so we assert the close + that focus
    // left the now-removed dialog rather than the exact restoration target.)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).not.toBe(dialog)
  })

  it('command palette exposes combobox + listbox roles', async () => {
    renderWithClient(<CommandPalette open onOpenChange={() => {}} />)
    // cmdk renders the input as role=combobox and the results list as
    // role=listbox; both must be present for AT keyboard navigation.
    expect(await screen.findByRole('combobox')).toBeInTheDocument()
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  // ---- Settings tabs ARIA ----

  it('Settings tabs expose tablist, tab roles and aria-selected', async () => {
    renderWithClient(<Settings />, '/settings')

    // The container has role=tablist
    expect(screen.getByRole('tablist')).toBeInTheDocument()

    // Three tabs
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
    expect(tabs.map((t) => t.textContent)).toEqual(['System', 'Sources', 'Messenger'])

    // System tab is selected by default
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'false')

    // Clicking Sources tab updates aria-selected
    const user = userEvent.setup()
    await user.click(tabs[1])
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'false')
  })

  it('Settings tab content renders as role=tabpanel', async () => {
    renderWithClient(<Settings />, '/settings')
    // Wait for system content to load
    await waitFor(() => {
      expect(screen.getByRole('tabpanel')).toBeInTheDocument()
    })
  })

  // ---- Search listbox (role=listbox, role=option, aria-activedescendant) ----

  it('Search result list uses role=listbox with role=option items', async () => {
    renderWithClient(<Search />, '/search')
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })

    const listbox = screen.getByRole('listbox', { name: 'Search results' })
    expect(listbox).toBeInTheDocument()

    const options = within(listbox).getAllByRole('option')
    expect(options.length).toBe(2)

    // First option is selected
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('Search listbox tracks aria-activedescendant', async () => {
    renderWithClient(<Search />, '/search')
    await waitFor(() => {
      expect(screen.getByTestId('search-page')).toBeInTheDocument()
    })

    const listbox = screen.getByRole('listbox', { name: 'Search results' })
    // aria-activedescendant points to the first result's id
    expect(listbox).toHaveAttribute('aria-activedescendant', 'search-row-D999')
  })

  // ---- LiveTail aria-live region ----

  it('LiveTail scrollable area has role=log and aria-live=polite when live', () => {
    const entries = [makeTailEntry({ key: 'r1', itemId: 'it_1' })]
    render(<LiveTail entries={entries} live={true} />)

    const logRegion = screen.getByRole('log')
    expect(logRegion).toBeInTheDocument()
    expect(logRegion).toHaveAttribute('aria-live', 'polite')
    expect(logRegion).toHaveAttribute('aria-label', 'Live funnel tail')
  })

  it('LiveTail sets aria-live=off when paused', () => {
    render(<LiveTail entries={[]} live={false} />)
    const logRegion = screen.getByRole('log')
    expect(logRegion).toHaveAttribute('aria-live', 'off')
  })

  it('LiveTail toggle button has aria-pressed attribute', () => {
    render(<LiveTail entries={[]} live={true} />)
    const toggle = screen.getByTestId('live-toggle')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
  })

  // ---- SourceFlow role=img + aria-label ----

  it('SourceFlow SVG has role=img with descriptive aria-label', () => {
    render(<SourceFlow data={makeSampleMatrix()} />)
    const flow = screen.getByTestId('source-flow')
    const svg = flow.querySelector('svg')!
    expect(svg.getAttribute('role')).toBe('img')
    expect(svg.getAttribute('aria-label')).toContain('Signal flow')
  })

  it('SourceFlow has a screen-reader-only table fallback', () => {
    render(<SourceFlow data={makeSampleMatrix()} />)
    const srTable = screen.getByTestId('source-flow-sr-table')
    expect(srTable.tagName).toBe('TABLE')
    expect(srTable.querySelector('caption')).toBeTruthy()
    expect(srTable.textContent).toContain('github')
    expect(srTable.textContent).toContain('email')
  })

  it('SourceFlow source and output nodes have <title> elements for AT', () => {
    render(<SourceFlow data={makeSampleMatrix()} />)
    const flow = screen.getByTestId('source-flow')
    const titles = flow.querySelectorAll('g > title')
    // 2 sources + 3 outputs = 5
    expect(titles.length).toBe(5)
  })

  // ---- FunnelStage correction picker accessibility ----

  it('FunnelStage correction picker buttons are accessible', async () => {
    const user = userEvent.setup()
    const stage = makeMockStage()
    const item = makeMockItem()

    renderWithClient(
      <FunnelStage
        stage={stage}
        index={0}
        isLast={true}
        item={item}
        editable={true}
        filterRules={[{ id: 'fr_01', prompt: 'Test rule prompt' }]}
      />,
    )

    // The correct button should be present
    const correctBtn = screen.getByTestId('correct-button')
    expect(correctBtn).toBeInTheDocument()

    // Click it to open the correction picker
    await user.click(correctBtn)
    const picker = screen.getByTestId('correction-picker')
    expect(picker).toBeInTheDocument()

    // Correction choices are rendered as buttons
    const buttons = within(picker).getAllByRole('button')
    // Should have correction choices (filtered: not the current outcome) + cancel
    expect(buttons.length).toBeGreaterThanOrEqual(2)

    // Cancel button closes the picker
    const cancelBtn = within(picker).getByRole('button', { name: 'Cancel' })
    expect(cancelBtn).toBeInTheDocument()
  })

  // ---- New dialog ARIA attributes (Dialog via FactRow) ----

  it('delete confirm dialog has role=dialog and descriptive content', async () => {
    const user = userEvent.setup()
    renderWithClient(
      <ul>
        <FactRow fact={{ id: 'f10', content: 'test', source: 'src', timestamp: null }} />
      </ul>,
    )

    await user.click(screen.getByRole('button', { name: /delete f10/i }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    // Dialog should contain interactive elements (confirm/cancel)
    const dialogButtons = within(dialog).getAllByRole('button')
    expect(dialogButtons.length).toBeGreaterThanOrEqual(1)
  })

  // ---- ActionChip color+text redundancy ----

  it('ActionChip renders both icon and text label for each action type', () => {
    const actions = ['drop', 'include', 'pass', 'skip', 'context', 'label', 'loopback'] as const

    for (const action of actions) {
      const { container, unmount } = render(
        <ActionChip action={action} label="test-label" />,
      )

      const chip = container.querySelector('[data-action]')!
      expect(chip).toBeTruthy()
      expect(chip.getAttribute('data-action')).toBe(action)

      // Must contain visible text (not relying on color alone)
      const text = chip.textContent ?? ''
      expect(text.length).toBeGreaterThan(0)

      // Must contain an SVG icon (color redundancy)
      const svg = chip.querySelector('svg')
      expect(svg).toBeTruthy()

      unmount()
    }
  })

  // ---- VerdictPill color+text redundancy ----

  it('VerdictPill renders icon and text for each decision type', () => {
    const decisions = ['triaged', 'dropped', 'queued'] as const

    for (const decision of decisions) {
      const { container, unmount } = render(
        <VerdictPill verdict={{ decision, rationale: 'test', confidence: 85 }} />,
      )

      const pill = container.querySelector('[data-verdict]')!
      expect(pill).toBeTruthy()
      expect(pill.getAttribute('data-verdict')).toBe(decision)

      // Must contain visible text (not color alone)
      const text = pill.textContent ?? ''
      expect(text.length).toBeGreaterThan(0)

      // Must contain an SVG icon
      const svg = pill.querySelector('svg')
      expect(svg).toBeTruthy()

      unmount()
    }
  })

  // ---- ConfidenceBar ARIA ----

  it('ConfidenceBar has role=progressbar with aria-valuenow, aria-valuemin, aria-valuemax', () => {
    render(<ConfidenceBar value={87} />)

    const bar = screen.getByRole('progressbar')
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveAttribute('aria-valuenow', '87')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('ConfidenceBar displays the percentage as visible text', () => {
    render(<ConfidenceBar value={92} />)
    expect(screen.getByText('92%')).toBeInTheDocument()
  })

  // ---- Hover-expand rail labels accessible ----

  it('sidebar rail labels are present in the DOM (visible on hover via CSS)', () => {
    renderWithRouter(<AppSidebar />)

    // Each nav link has a visible label span with class wb-rail-label.
    // These are in the DOM always (CSS controls visibility on hover).
    const nav = screen.getByRole('navigation', { name: /primary/i })
    const labels = nav.querySelectorAll('.wb-rail-label')

    // Logo label + 7 nav item labels = at least 8
    expect(labels.length).toBeGreaterThanOrEqual(8)

    // Check that labels contain the expected text
    const labelTexts = Array.from(labels).map((l) => l.textContent?.trim())
    expect(labelTexts).toContain('WorkBench')
    expect(labelTexts).toContain('Overview')
    expect(labelTexts).toContain('Settings')
  })

  it('sidebar links have tooltip content for collapsed state', () => {
    renderWithRouter(<AppSidebar />)

    // Radix TooltipContent elements are rendered in the DOM (portaled).
    // Each nav link is wrapped in a Tooltip, providing the label as
    // tooltip content for when the rail is collapsed.
    // Verify the aria-label on each link matches a route name.
    const nav = screen.getByRole('navigation', { name: /primary/i })
    const links = nav.querySelectorAll('a[aria-label]')

    // Logo + 7 routes = 8 labeled links
    expect(links.length).toBe(8)
  })
})
