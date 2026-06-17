import { describe, expect, it } from 'vitest'
import type { Enricher, FunnelItem, FunnelStage } from './types/funnel'
import { buildFlowMatrix, enricherStageFor, itemLog, stageDuration, stageTimings } from './funnel-helpers'

const makeItem = (overrides: Partial<FunnelItem> = {}): FunnelItem => ({
  id: 1,
  summary: 'Test item',
  source: 'github',
  created_at: '2026-06-11T00:00:00Z',
  stages: [
    { filterId: 'fr_01', outcome: 'drop', confidence: 90 },
  ],
  verdict: { decision: 'dropped', confidence: 90, rationale: 'test' },
  ...overrides,
})

const githubEnricher: Enricher = {
  id: 101,
  type: 'github',
  label: 'GitHub enricher',
  depth: 'shallow',
  enabled: true,
  adds: ['author', 'ci', 'files_changed'],
  records: ['person', 'repo'],
  budget: { max_calls: 1, max_time_ms: 5000 },
  avg_ms: 12,
  enriched: 100,
}

describe('enricherStageFor', () => {
  it('returns an enrichment stage for a matching source', () => {
    const result = enricherStageFor({ id: 1, source: 'github' }, [githubEnricher])
    expect(result).not.toBeNull()
    expect(result!.filterId).toBe('101')
    expect(result!.outcome).toBe('context')
    expect(result!.context).toContain('author')
  })

  it('returns null when no enricher matches the source', () => {
    const result = enricherStageFor({ id: 1, source: 'unknown' }, [githubEnricher])
    expect(result).toBeNull()
  })
})

describe('itemLog', () => {
  it('prepends enricher stage when not already present', () => {
    const item = makeItem({ source: 'github' })
    const log = itemLog(item, [githubEnricher])
    expect(log[0].filterId).toBe('101')
    expect(log[0].outcome).toBe('context')
    expect(log.length).toBe(2)
  })

  it('does not prepend when stages already start with enricher', () => {
    const item = makeItem({
      stages: [
        { filterId: 'en_github', outcome: 'context' },
        { filterId: 'fr_01', outcome: 'drop' },
      ],
    })
    const log = itemLog(item, [githubEnricher])
    expect(log.length).toBe(2)
  })

  it('returns base stages when no enrichers provided', () => {
    const item = makeItem()
    const log = itemLog(item)
    expect(log).toEqual(item.stages)
  })
})

describe('stageDuration', () => {
  it('returns deterministic values for the same filterId', () => {
    const stage: FunnelStage = { filterId: 'fr_31', outcome: 'drop' }
    const d1 = stageDuration(stage)
    const d2 = stageDuration(stage)
    expect(d1).toBe(d2)
  })

  it('enricher stages are shorter (6-19ms)', () => {
    const stage: FunnelStage = { filterId: 'en_github', outcome: 'context' }
    const dur = stageDuration(stage)
    expect(dur).toBeGreaterThanOrEqual(6)
    expect(dur).toBeLessThanOrEqual(19)
  })

  it('filter stages are longer (36-155ms)', () => {
    const stage: FunnelStage = { filterId: 'fr_01', outcome: 'drop' }
    const dur = stageDuration(stage)
    expect(dur).toBeGreaterThanOrEqual(36)
    expect(dur).toBeLessThanOrEqual(155)
  })
})

describe('stageTimings', () => {
  it('produces cumulative timings', () => {
    const stages: FunnelStage[] = [
      { filterId: 'en_github', outcome: 'context' },
      { filterId: 'fr_01', outcome: 'drop' },
      { filterId: 'fr_02', outcome: 'pass' },
    ]
    const timings = stageTimings(stages)
    expect(timings).toHaveLength(3)
    expect(timings[0].at).toBe(0)
    expect(timings[1].at).toBe(timings[0].dur)
    expect(timings[2].at).toBe(timings[0].dur + timings[1].dur)
  })
})

describe('buildFlowMatrix', () => {
  it('distributes source volumes proportionally across output buckets', () => {
    const matrix = buildFlowMatrix(
      { github: 600, email: 400 },
      { action_items: 250, triage_queue: 250, filtered_out: 400, errors: 100 },
    )
    expect(matrix.sources).toHaveLength(2)
    expect(matrix.outputs).toHaveLength(4)
    expect(matrix.matrix).toHaveLength(2)

    for (let i = 0; i < matrix.sources.length; i++) {
      const rowSum = matrix.matrix[i].reduce((s, v) => s + v, 0)
      expect(rowSum).toBeCloseTo(matrix.sources[i].vol, -1)
    }
  })

  it('output columns sum to bucket totals (approximately)', () => {
    const matrix = buildFlowMatrix(
      { github: 600, email: 400 },
      { action_items: 250, triage_queue: 250, filtered_out: 400, errors: 100 },
    )
    for (let j = 0; j < 4; j++) {
      const colSum = matrix.matrix.reduce((s, row) => s + row[j], 0)
      expect(colSum).toBeCloseTo(matrix.outputs[j].vol, -1)
    }
  })

  it('handles single source', () => {
    const matrix = buildFlowMatrix(
      { github: 100 },
      { action_items: 25, triage_queue: 25, filtered_out: 40, errors: 10 },
    )
    expect(matrix.sources).toHaveLength(1)
    expect(matrix.matrix).toHaveLength(1)
  })

  it('handles all-zero output', () => {
    const matrix = buildFlowMatrix(
      { github: 100 },
      { action_items: 0, triage_queue: 0, filtered_out: 0, errors: 0 },
    )
    expect(matrix.matrix[0]).toEqual([0, 0, 0, 0])
  })

  it('handles empty source volumes', () => {
    const matrix = buildFlowMatrix(
      {},
      { action_items: 10, triage_queue: 10, filtered_out: 10, errors: 10 },
    )
    expect(matrix.sources).toHaveLength(0)
    expect(matrix.matrix).toHaveLength(0)
  })

  it('maintains fixed output order: action_items, triage_queue, filtered_out, errors', () => {
    const matrix = buildFlowMatrix(
      { github: 100 },
      { action_items: 10, triage_queue: 20, filtered_out: 60, errors: 10 },
    )
    expect(matrix.outputs.map((o) => o.id)).toEqual([
      'action_items', 'triage_queue', 'filtered_out', 'errors',
    ])
  })
})
