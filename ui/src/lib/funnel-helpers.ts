import type { Enricher, FunnelItem, FunnelStage } from './types/funnel'

export interface TimingInfo {
  at: number
  dur: number
}

export interface FlowMatrixSource {
  id: string
  label: string
  vol: number
}

export interface FlowMatrixOutput {
  id: string
  label: string
  vol: number
}

export interface FlowMatrix {
  sources: FlowMatrixSource[]
  outputs: FlowMatrixOutput[]
  matrix: number[][]
}

function hashNum(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

export function ruleById(
  id: string,
  filterRules: Array<{ id: number | string; prompt: string }>,
  enrichers?: Array<{ id: number | string; label: string }>,
): { prompt: string } {
  const rule = filterRules.find((r) => String(r.id) === id)
  if (rule) return rule
  const enr = enrichers?.find((e) => String(e.id) === id)
  if (enr) return { prompt: `${enr.label} — adds context to the item` }
  return { prompt: id }
}

export function enricherStageFor(
  item: { id: number; source: string },
  enrichers: Enricher[],
  enrichmentSamples?: Record<string, Array<{ id: number; context: Record<string, string | number | boolean> }>>,
): FunnelStage | null {
  const enr = enrichers.find((e) => e.type === item.source)
  if (!enr) return null
  const sample = enrichmentSamples?.[enr.id]?.find((x) => x.id === item.id)
  const ctxStr = sample
    ? Object.entries(sample.context).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(' · ')
    : enr.adds.slice(0, 4).join(' · ')
  return {
    filterId: String(enr.id),
    outcome: 'context',
    reason: `${enr.label} resolved metadata and recorded ${enr.records.join(' + ')} to memory.`,
    context: ctxStr,
  }
}

export function itemLog(
  item: FunnelItem,
  enrichers?: Enricher[],
  enrichmentSamples?: Record<string, Array<{ id: number; context: Record<string, string | number | boolean> }>>,
): FunnelStage[] {
  const base = item.stages ?? []
  if (base.length > 0 && String(base[0].filterId).startsWith('en_')) return base
  if (!enrichers) return base
  const en = enricherStageFor(item, enrichers, enrichmentSamples)
  return en ? [en, ...base] : base
}

export function stageDuration(stage: FunnelStage): number {
  const id = String(stage.filterId)
  const h = hashNum(id)
  if (id.startsWith('en_')) {
    return 6 + (h % 14)
  }
  return 36 + (h % 120)
}

export function stageTimings(log: FunnelStage[]): TimingInfo[] {
  let at = 0
  return log.map((st) => {
    const dur = stageDuration(st)
    const o = { at, dur }
    at += dur
    return o
  })
}

/**
 * Catmull-Rom smoothed SVG path from a series of [x, y] points.
 * Used by MultiLineChart and SmoothSparkline for organic curves.
 */
export function smoothPath(pts: number[][]): string {
  if (pts.length < 2) return ''
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`
  }
  return d
}

export function buildFlowMatrix(
  sourceVolumes: Record<string, number>,
  outputBuckets: { action_items: number; triage_queue: number; filtered_out: number; errors: number },
): FlowMatrix {
  const sourceEntries = Object.entries(sourceVolumes).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  const outputEntries: Array<[string, number]> = [
    ['action_items', outputBuckets.action_items],
    ['triage_queue', outputBuckets.triage_queue],
    ['filtered_out', outputBuckets.filtered_out],
    ['errors', outputBuckets.errors],
  ]

  const outputLabels: Record<string, string> = {
    action_items: 'Action Items',
    triage_queue: 'Triage Queue',
    filtered_out: 'Filtered Out',
    errors: 'Errors',
  }

  const sources: FlowMatrixSource[] = sourceEntries.map(([id, vol]) => ({ id, label: id, vol }))
  const outputs: FlowMatrixOutput[] = outputEntries.map(([id, vol]) => ({ id, label: outputLabels[id] ?? id, vol }))

  const totalOutput = outputEntries.reduce((s, [, v]) => s + v, 0)
  if (totalOutput === 0 || sources.length === 0) {
    return { sources, outputs, matrix: sources.map(() => [0, 0, 0, 0]) }
  }

  const outputRatios = outputEntries.map(([, v]) => v / totalOutput)
  const matrix = sources.map((s) => outputRatios.map((ratio) => Math.round(s.vol * ratio)))

  return { sources, outputs, matrix }
}
