// Shared MSW handlers for all API endpoints.
//
// Export `handlers` as the base handler set and `server` as a pre-configured
// MSW server.  Individual test files may import `handlers` and extend or
// override them via `server.use(...)`.
//
// These handlers return realistic mock data that matches the shapes defined in
// src/lib/types/ and the Python domain models.

import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import type { ServerCorrection, ServerTuningTask } from '@/hooks/useFeedback'
import type {
  FilterRuleExtended,
  Enricher,
  LoopBack,
  FunnelItem,
  FunnelOrderEntry,
  EnrichmentSample,
} from '@/lib/types/funnel'

// ---------------------------------------------------------------------------
// Feedback mock data
// ---------------------------------------------------------------------------

const CORRECTIONS: ServerCorrection[] = [
  {
    id: 1,
    item_id: 1,
    rule_id: 1,
    original_action: 'drop',
    corrected_action: 'include',
    reason: 'This CI notification was actually relevant to my deploy',
    created_at: '2026-06-09T08:30:00Z',
  },
  {
    id: 2,
    item_id: 2,
    rule_id: null,
    original_action: 'include',
    corrected_action: 'drop',
    reason: null,
    created_at: '2026-06-09T10:15:00Z',
  },
]

const TUNING_TASKS: ServerTuningTask[] = [
  {
    id: 1,
    rule_id: 1,
    proposed_prompt:
      'Drop CI notifications about passing builds — but kept and surfaced cases like "Deploy notification for my service" (you corrected this).',
    correction_ids: [1],
    status: 'open',
    created_at: '2026-06-09T08:31:00Z',
    resolved_at: null,
  },
  {
    id: 2,
    rule_id: 2,
    proposed_prompt: 'Include any diff mentioning my team — refined.',
    correction_ids: [2],
    status: 'applied',
    created_at: '2026-06-09T10:16:00Z',
    resolved_at: '2026-06-09T10:20:00Z',
  },
]

// ---------------------------------------------------------------------------
// Funnel mock data
// ---------------------------------------------------------------------------

const FILTER_RULES: FilterRuleExtended[] = [
  {
    id: 1,
    prompt: 'Drop CI notifications about passing builds',
    action: 'drop',
    sources: ['github'],
    confidence: 92,
    origin: 'learned',
    matched: 14,
    enabled: true,
    order_index: 0,
  },
  {
    id: 2,
    prompt: 'Include any diff mentioning my team',
    action: 'include',
    sources: ['github', 'email'],
    confidence: 88,
    origin: 'explicit',
    matched: 7,
    enabled: true,
    order_index: 1,
  },
]

const ENRICHERS: Enricher[] = [
  {
    id: 101,
    type: 'github',
    label: 'GitHub Metadata',
    depth: 'shallow',
    enabled: true,
    adds: ['author', 'files_changed', 'ci_status'],
    records: ['people', 'repos'],
    budget: { max_calls: 1, max_time_ms: 5000 },
    avg_ms: 12,
    enriched: 42,
  },
]

const LOOPBACKS: LoopBack[] = [
  {
    id: 201,
    label: 'Re-push stale',
    trigger: 'When an item was triaged >24h ago but no action taken',
    condition: 'status === "triaged" && age_hours > 24',
    max_loops: 2,
    enabled: true,
    looped: 3,
    avg_loops: 1.5,
  },
]

const FUNNEL_ITEMS: FunnelItem[] = [
  {
    id: 1,
    summary: 'PR #42: Fix login bug',
    source: 'github',
    created_at: '2026-06-10T12:00:00Z',
    stages: [
      {
        filterId: 'en_github',
        outcome: 'context',
        reason: 'GitHub Metadata resolved metadata.',
        context: 'author: alice · files: 3',
      },
      {
        filterId: 'fr_01',
        outcome: 'pass',
        reason: 'Not a CI notification.',
        confidence: 95,
      },
      {
        filterId: 'fr_02',
        outcome: 'include',
        reason: 'Mentions your team.',
        confidence: 88,
      },
    ],
    verdict: {
      decision: 'triaged',
      priority: 'P1',
      confidence: 91,
      rationale: 'Relevant to your team based on two filter signals.',
    },
  },
  {
    id: 2,
    summary: 'Weekly ops digest',
    source: 'email',
    created_at: '2026-06-10T06:00:00Z',
    stages: [
      {
        filterId: 'fr_01',
        outcome: 'drop',
        reason: 'Matched noise pattern.',
        confidence: 78,
      },
    ],
    verdict: {
      decision: 'dropped',
      confidence: 78,
      rationale: 'Low-value recurring digest.',
    },
  },
]

const FUNNEL_ORDER: FunnelOrderEntry[] = [
  { kind: 'enricher', id: 101 },
  { kind: 'filter', id: 1 },
  { kind: 'filter', id: 2 },
  { kind: 'loopback', id: 201 },
]

const ENRICHMENT_SAMPLES: Record<string, EnrichmentSample[]> = {
  '101': [
    {
      id: 1,
      summary: 'PR #42: Fix login bug',
      context: { author: 'alice', files_changed: 3, ci_status: 'passing' },
      entities: ['alice', 'meta/workbench'],
    },
  ],
}

// ---------------------------------------------------------------------------
// Search mock data (SearchItem shape via /api/items/search)
// ---------------------------------------------------------------------------

const SEARCH_RESULTS = [
  {
    id: 12345,
    source_type: 'diff',
    source_id: 'D12345',
    summary: 'Fix auth middleware race condition',
    category: 'action_item',
    origin: 'phabricator',
    priority: 'P1',
    status: 'triaged',
    path: '2.1',
    created_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    updated_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    tags: ['security', 'auth'],
    llm_summary: 'Critical race condition fix in auth middleware.',
    enriched_context: { type: 'diff', author: 'alice', team: 'infra', status: 'Needs Review', url: 'https://phabricator.example.com/D12345', hunks: [] },
    processing_log: [{ stage: 'f_relevance', outcome: 'include', label: 'High relevance' }],
    verdict: { action: 'triage', priority: 'P1', confidence: 92 },
  },
]

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export function handlers() {
  return [
    // Auth
    http.get('/api/auth/token', () => HttpResponse.json({ token: 'test-token' })),

    // ---------- Feedback corrections ----------
    http.get('/api/feedback/corrections', ({ request }) => {
      const url = new URL(request.url)
      const itemId = url.searchParams.get('item_id')
      const result = itemId
        ? CORRECTIONS.filter((c) => String(c.item_id) === itemId)
        : CORRECTIONS
      return HttpResponse.json(result)
    }),

    http.post('/api/feedback/corrections', async ({ request }) => {
      const body = (await request.json()) as Partial<ServerCorrection>
      const created: ServerCorrection = {
        id: Math.floor(Math.random() * 1_000_000),
        item_id: body.item_id ?? 99,
        rule_id: body.rule_id ?? null,
        original_action: body.original_action ?? 'pass',
        corrected_action: body.corrected_action ?? 'include',
        reason: body.reason ?? null,
        created_at: new Date().toISOString(),
      }
      return HttpResponse.json(created, { status: 201 })
    }),

    http.delete('/api/feedback/corrections/:id', () =>
      HttpResponse.json({ status: 'deleted' }),
    ),

    // ---------- Feedback tuning tasks ----------
    http.get('/api/feedback/tasks', ({ request }) => {
      const url = new URL(request.url)
      const status = url.searchParams.get('status')
      const result = status
        ? TUNING_TASKS.filter((t) => t.status === status)
        : TUNING_TASKS
      return HttpResponse.json(result)
    }),

    http.post('/api/feedback/tasks', async ({ request }) => {
      const body = (await request.json()) as Partial<ServerTuningTask>
      const created: ServerTuningTask = {
        id: Math.floor(Math.random() * 1_000_000),
        rule_id: body.rule_id ?? 99,
        proposed_prompt: body.proposed_prompt ?? 'refined prompt',
        correction_ids: body.correction_ids ?? [],
        status: body.status ?? 'open',
        created_at: new Date().toISOString(),
        resolved_at: null,
      }
      return HttpResponse.json(created, { status: 201 })
    }),

    http.patch('/api/feedback/tasks/:taskId', ({ request, params }) => {
      const url = new URL(request.url)
      const newStatus = url.searchParams.get('status') ?? 'applied'
      const task = TUNING_TASKS.find((t) => String(t.id) === params.taskId)
      if (!task) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      return HttpResponse.json({ ...task, status: newStatus, resolved_at: new Date().toISOString() })
    }),

    http.delete('/api/feedback/tasks/:taskId', () =>
      HttpResponse.json({ status: 'deleted' }),
    ),

    // ---------- Funnel ----------
    http.get('/api/funnel/filter-rules', () => HttpResponse.json(FILTER_RULES)),
    http.get('/api/funnel/enrichers', () => HttpResponse.json(ENRICHERS)),
    http.get('/api/funnel/loopbacks', () => HttpResponse.json(LOOPBACKS)),
    http.get('/api/funnel/items', () => HttpResponse.json(FUNNEL_ITEMS)),
    http.get('/api/funnel/items/:id', ({ params }) => {
      const item = FUNNEL_ITEMS.find((it) => String(it.id) === params.id)
      return item
        ? HttpResponse.json(item)
        : HttpResponse.json({ detail: 'not found' }, { status: 404 })
    }),
    http.get('/api/funnel/order', () => HttpResponse.json(FUNNEL_ORDER)),
    http.get('/api/funnel/enrichment-samples', () =>
      HttpResponse.json(ENRICHMENT_SAMPLES),
    ),

    http.patch('/api/funnel/order', () =>
      HttpResponse.json({ status: 'ok' }),
    ),

    http.post('/api/funnel/stages/:id/toggle', () =>
      HttpResponse.json({ status: 'ok' }),
    ),

    http.post('/api/funnel/filter-rules', async ({ request }) => {
      const body = (await request.json()) as Partial<FilterRuleExtended>
      const created: FilterRuleExtended = {
        id: Math.floor(Math.random() * 1_000_000),
        prompt: body.prompt ?? '',
        action: body.action ?? 'drop',
        sources: body.sources ?? [],
        confidence: null,
        origin: 'explicit',
        matched: 0,
        enabled: true,
        order_index: FILTER_RULES.length,
      }
      return HttpResponse.json(created, { status: 201 })
    }),

    http.delete('/api/funnel/filter-rules/:id', () =>
      HttpResponse.json({ status: 'deleted' }),
    ),

    // ---------- Enrichers detail + samples ----------
    http.get('/api/enrichers', () => HttpResponse.json(ENRICHERS)),

    http.get('/api/enrichers/:id', ({ params }) => {
      const enricher = ENRICHERS.find((e) => String(e.id) === params.id)
      return enricher
        ? HttpResponse.json(enricher)
        : HttpResponse.json({ detail: 'not found' }, { status: 404 })
    }),

    http.get('/api/enrichers/:id/samples', ({ params }) => {
      const samples = ENRICHMENT_SAMPLES[params.id as string] ?? []
      return HttpResponse.json(samples)
    }),

    // ---------- Loopbacks detail ----------
    http.get('/api/loopbacks', () => HttpResponse.json(LOOPBACKS)),

    http.get('/api/loopbacks/:id', ({ params }) => {
      const lb = LOOPBACKS.find((l) => String(l.id) === params.id)
      return lb
        ? HttpResponse.json(lb)
        : HttpResponse.json({ detail: 'not found' }, { status: 404 })
    }),

    // ---------- Search ----------
    http.get('/api/items/search', () =>
      HttpResponse.json({ q: '', results: SEARCH_RESULTS, total: SEARCH_RESULTS.length }),
    ),

    http.get('/api/items/by-id/:id', ({ params }) => {
      const found = SEARCH_RESULTS.find((r) => String(r.id) === params.id)
      return found
        ? HttpResponse.json(found)
        : new HttpResponse(JSON.stringify({ detail: 'Item not found' }), { status: 404 })
    }),

    // ---------- Item actions ----------
    http.post('/api/items/:id/snooze', () =>
      HttpResponse.json({ status: 'ok' }),
    ),

    http.post('/api/items/:id/archive', () =>
      HttpResponse.json({ status: 'ok' }),
    ),

    http.post('/api/items/:id/boost', () =>
      HttpResponse.json({ status: 'ok' }),
    ),

    // ---------- Filter rules CRUD ----------
    http.patch('/api/filter-rules/:id', async ({ request, params }) => {
      const body = (await request.json()) as Partial<FilterRuleExtended>
      const rule = FILTER_RULES.find((r) => String(r.id) === params.id)
      if (!rule) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      return HttpResponse.json({ ...rule, ...body })
    }),

    http.delete('/api/filter-rules/:id', () =>
      HttpResponse.json({ status: 'deleted' }),
    ),

    http.patch('/api/filter-rules/:id/prompt', async ({ request, params }) => {
      const body = (await request.json()) as { prompt: string }
      const rule = FILTER_RULES.find((r) => String(r.id) === params.id)
      if (!rule) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      return HttpResponse.json({ ...rule, prompt: body.prompt })
    }),
  ]
}

// Pre-configured server with all handlers. Tests can import and extend.
export const server = setupServer(...handlers())
