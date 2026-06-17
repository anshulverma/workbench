import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { TriageDetail } from './TriageDetail'
import { _resetToken } from '@/lib/api'

const CARD = {
  id: 'c1',
  status: 'sent',
  relevance_score: 80,
  options: [{ label: 'Add P1', action: 'add_todo' }, { label: 'Skip', action: 'skip' }],
  card_content: {
    content_schema: 'diff.v1',
    summary: 'Adds a retry loop',
    sections: {
      metadata: { author: 'alice', team: 'infra', status: 'needs_review' },
      summary: 'Adds a retry loop',
      risk: { factors: ['touches retry path'], watch_outs: ['no test'] },
      why_care: 'You own this client',
      hunks: [{ file: 'client.py', header: '@@ -1 +1,2 @@', code: '+retry()', annotation: 'adds retry', rank: 1 }],
      diff_url: 'https://phab/D123',
    },
  },
}

// A non-diff (task) card: no diff `sections`, but carries universal source
// identity (source_type / source_ref / source_url).
const CARD_TASK = {
  id: 'c2',
  status: 'sent',
  relevance_score: 60,
  options: [{ label: 'Add P1', action: 'add_todo' }],
  card_content: {
    summary: 'Investigate flaky test',
    source_type: 'meta_tasks',
    source_ref: 'T123456',
    source_url: 'https://www.internalfb.com/tasks/?t=123456',
  },
}

const server = setupServer(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers(http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok' })))
  _resetToken()
})
afterAll(() => server.close())

function renderDetail(id = 'c1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/triage/${id}`]}>
        <Routes>
          <Route path="/triage/:cardId" element={<TriageDetail />} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TriageDetail', () => {
  it('renders metadata + summary visible and the Phabricator link', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText('Adds a retry loop')).toBeInTheDocument()
    expect(screen.getByText(/alice/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /View in Phabricator/i })
    expect(link).toHaveAttribute('href', 'https://phab/D123')
  })

  it('shows risk + why-care expanded by default', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText(/touches retry path/)).toBeInTheDocument()
    expect(screen.getByText(/You own this client/)).toBeInTheDocument()
  })

  it('renders the diff hunks', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByText('client.py')).toBeInTheDocument()
    expect(screen.getByText('+retry()')).toBeInTheDocument()
  })

  it('is read-only when the card status is responded', async () => {
    server.use(
      http.get('/api/triage/cards/c1', () =>
        HttpResponse.json({ ...CARD, status: 'responded' }),
      ),
    )
    renderDetail()
    await screen.findByText('Adds a retry loop')
    expect(screen.queryByRole('button', { name: /1\. Add P1/i })).not.toBeInTheDocument()
  })

  it('shows option buttons when the card is actionable (sent)', async () => {
    server.use(http.get('/api/triage/cards/c1', () => HttpResponse.json(CARD)))
    renderDetail()
    expect(await screen.findByRole('button', { name: /1\. Add P1/i })).toBeInTheDocument()
  })

  it('shows a source-type badge and an "open in source" link for a non-diff card', async () => {
    server.use(http.get('/api/triage/cards/c2', () => HttpResponse.json(CARD_TASK)))
    renderDetail('c2')
    expect(await screen.findByText('Investigate flaky test')).toBeInTheDocument()
    expect(screen.getByTestId('source-type-badge')).toHaveTextContent(/task/i)
    const link = screen.getByRole('link', { name: /T123456/ })
    expect(link).toHaveAttribute('href', 'https://www.internalfb.com/tasks/?t=123456')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('shows the change callout on a re-triaged card', async () => {
    server.use(
      http.get('/api/triage/cards/c1', () =>
        HttpResponse.json({
          ...CARD,
          card_content: {
            ...CARD.card_content,
            sections: {
              ...CARD.card_content.sections,
              change: 'Status moved needs_review -> accepted since you last triaged.',
            },
          },
        }),
      ),
    )
    renderDetail()
    expect(await screen.findByText(/What changed since last triage/i)).toBeInTheDocument()
    expect(screen.getByText(/needs_review -> accepted/)).toBeInTheDocument()
  })
})
