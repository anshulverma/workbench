// search-adapter.ts — single source of truth for mapping the rich item API shape
// (from /api/items/search and /api/items/by-id/{id}) to the UI's SearchItem type.
// Replaces the old `as unknown as SearchItem[]` cast that hid a shape mismatch.

import type { SearchItem, ItemKind, ItemState, ItemContext } from '@/lib/types/search'
import type { Verdict, FunnelStage, StageOutcome } from '@/lib/types/funnel'

interface ApiLogEntry {
  stage?: string | null
  filterId?: string | null
  outcome?: string | null
  reason?: string | null
  label?: string | null
  confidence?: number | null
}

export interface ApiSearchItem {
  id: number
  source_type?: string | null
  source_id?: string | null
  summary?: string | null
  category?: string | null
  origin?: string | null
  priority?: string | null
  status?: string | null
  kind?: string | null
  path?: string | null
  created_at?: string | null
  updated_at?: string | null
  tags?: string[] | null
  llm_summary?: string | null
  enriched_context?: Record<string, unknown> | null
  processing_log?: ApiLogEntry[] | null
  verdict?: { action?: string | null; priority?: string | null; confidence?: number | null } | null
}

function mapStage(e: ApiLogEntry): FunnelStage {
  return {
    filterId: String(e.stage ?? e.filterId ?? ''),
    outcome: (e.outcome ?? 'pass') as StageOutcome,
    reason: e.reason ?? e.label ?? undefined,
    label: e.label ?? undefined,
    confidence: e.confidence ?? undefined,
  }
}

function mapVerdict(v: ApiSearchItem['verdict']): Verdict {
  const action = v?.action
  const decision: Verdict['decision'] =
    action === 'drop' ? 'dropped' : action === 'triaged' ? 'triaged' : 'queued'
  return {
    decision,
    priority: v?.priority ?? undefined,
    confidence: v?.confidence ?? undefined,
    rationale: '',
  }
}

export function toSearchItem(api: ApiSearchItem): SearchItem {
  const ctx = api.enriched_context
  const hasCtx = !!ctx && typeof ctx === 'object' && Object.keys(ctx).length > 0
  return {
    id: api.id,
    kind: (api.source_type ?? '') as ItemKind,
    path: api.path ?? undefined,
    summary: api.summary ?? '',
    source: api.source_type ?? '',
    priority: api.priority ?? null,
    state: (api.status ?? 'pending_triage') as ItemState,
    relevance: 0,
    tags: api.tags ?? [],
    created_at: api.created_at ?? '',
    llm_summary: api.llm_summary ?? '',
    context: hasCtx ? (ctx as unknown as ItemContext) : null,
    stages: (api.processing_log ?? []).map(mapStage),
    verdict: mapVerdict(api.verdict),
  }
}
