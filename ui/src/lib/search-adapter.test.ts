import { describe, expect, it } from 'vitest'
import { toSearchItem } from './search-adapter'

const API = {
  id: 7,
  source_type: 'diff',
  source_id: 'D1',
  summary: 'fix',
  category: 'action_item',
  origin: 'phabricator',
  priority: 'P2',
  status: 'pending_triage',
  kind: 'item',
  path: null,
  created_at: '2026-06-22T00:00:00Z',
  updated_at: '2026-06-22T00:00:00Z',
  tags: ['a'],
  llm_summary: 'why',
  enriched_context: { type: 'diff', author: 'x' },
  processing_log: [{ label: 'f', outcome: 'pass', stage: 'filter' }],
  verdict: { action: 'triage', priority: 'P2', confidence: 42 },
}

describe('toSearchItem', () => {
  it('maps the rich API shape to SearchItem', () => {
    const s = toSearchItem(API)
    expect(s.id).toBe(7)
    expect(s.kind).toBe('diff')
    expect(s.source).toBe('diff')
    expect(s.state).toBe('pending_triage')
    expect(s.priority).toBe('P2')
    expect(s.tags).toEqual(['a'])
    expect(s.llm_summary).toBe('why')
    expect(s.relevance).toBe(0)
    expect(s.context).toEqual({ type: 'diff', author: 'x' })
    // processing_log entries are mapped to FunnelStage shape (stage -> filterId, label -> reason)
    expect(s.stages).toEqual([
      { filterId: 'filter', outcome: 'pass', reason: 'f', label: 'f', confidence: undefined },
    ])
    expect(s.verdict.decision).toBe('queued')
    expect(s.verdict.rationale).toBe('')
  })

  it('applies safe defaults for missing/empty fields', () => {
    const s = toSearchItem({ id: 1, summary: 'x' } as unknown as Parameters<typeof toSearchItem>[0])
    expect(s.tags).toEqual([])
    expect(s.context).toBeNull()
    expect(s.stages).toEqual([])
    expect(s.priority).toBeNull()
    expect(s.path).toBeUndefined()
    expect(s.relevance).toBe(0)
  })

  it('maps verdict action "drop" to dropped', () => {
    const s = toSearchItem({ ...API, verdict: { action: 'drop' } } as never)
    expect(s.verdict.decision).toBe('dropped')
  })
})
