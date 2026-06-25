// EdgePredicateBadge — an HTML pill positioned over an edge midpoint showing the
// edge id (E{n}) and a short plain-text rendering of its predicate. `always`
// edges read muted; conditional edges read foreground.

import { predicateBadgeText } from '@/lib/pipeline/predicate'
import type { PipelineEdge } from '@/lib/types/pipeline'

export interface EdgePredicateBadgeProps {
  edge: PipelineEdge
  selected?: boolean
  onClick?: (edge: PipelineEdge) => void
}

export function EdgePredicateBadge({
  edge,
  selected,
  onClick,
}: EdgePredicateBadgeProps) {
  const isAlways = !edge.predicate || ('op' in edge.predicate && edge.predicate.op === 'always')
  const text = predicateBadgeText(edge.predicate)
  return (
    <button
      type="button"
      data-edgebadge
      onClick={(e) => {
        e.stopPropagation()
        onClick?.(edge)
      }}
      className="inline-flex cursor-pointer items-center gap-[5px] whitespace-nowrap rounded-[var(--radius-chip)] px-2 py-[3px] font-mono tracking-[0.02em]"
      style={{
        fontSize: 10.5,
        border: `1px solid ${selected ? 'var(--ring)' : 'var(--border)'}`,
        background: isAlways ? 'var(--surface-container)' : 'var(--surface-high)',
        color: isAlways ? 'var(--muted-foreground)' : 'var(--foreground)',
        boxShadow: '0 3px 12px rgba(0,0,0,.45)',
      }}
    >
      <span
        className="font-bold tabular-nums"
        style={{ color: 'var(--brand)' }}
      >
        E{edge.id}
      </span>
      <span>{text}</span>
    </button>
  )
}
