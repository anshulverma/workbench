// StageNode — an absolutely-positioned HTML card rendered over the SVG edge
// layer. Carries the node's icon/label, source-scope chips, live funnel counts,
// an enable Switch (or a Lock for reserved stages), and the type kicker.
// Geometry (left/top/width) must stay inline; everything else uses tokens.

import { Lock, Pin } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Mono } from '@/components/Mono'
import { NODE_META, NODE_STATS, nodeMeta } from '@/lib/pipeline/schema'
import type { PipelineNode } from '@/lib/types/pipeline'
import { NODE_W } from './geometry'
import { pipelineIcon } from './icons'

/** source-scope chips (e.g. DIFF · TASK) shown under a non-reserved node. */
function ScopeChips({ scope }: { scope: string[] | null }) {
  if (!scope || !scope.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {scope.map((s) => (
        <span
          key={s}
          className="rounded-[var(--radius-chip)] border border-border bg-[var(--surface-highest)] px-[5px] py-px font-mono uppercase tracking-[0.04em] text-muted-foreground"
          style={{ fontSize: 9.5 }}
        >
          {s}
        </span>
      ))}
    </div>
  )
}

/** live entered/dropped/passed funnel counts + a pass-rate bar. */
function NodeCounts({ stat }: { stat?: string }) {
  const s = stat ? NODE_STATS[stat] : undefined
  if (!s) return null
  const pct = s.entered ? Math.round((s.passed / s.entered) * 100) : 0
  return (
    <div className="grid gap-[3px]">
      <div
        className="flex items-baseline justify-between gap-1.5 font-mono"
        style={{ fontSize: 9.5 }}
      >
        <span className="whitespace-nowrap text-muted-foreground">
          {s.entered}
          <span className="opacity-60"> in</span>
        </span>
        {s.dropped > 0 && (
          <span className="whitespace-nowrap text-error-text">−{s.dropped}</span>
        )}
        <span className="whitespace-nowrap text-success">
          {s.passed}
          <span className="opacity-60"> ▸</span>
        </span>
      </div>
      <div className="h-[3px] overflow-hidden rounded-[2px] bg-[var(--surface-lowest)]">
        <div
          className="h-full"
          style={{
            width: `${pct}%`,
            background: s.dropped > 0 ? 'var(--brand)' : 'var(--success)',
          }}
        />
      </div>
    </div>
  )
}

export interface StageNodeProps {
  node: PipelineNode
  selected?: boolean
  dimmed?: boolean
  error?: boolean
  dropValid?: boolean
  onSelect?: (id: number) => void
  onToggle?: (id: number, enabled: boolean) => void
  onConfig?: (node: PipelineNode) => void
  draggable?: boolean
  onNodeMouseDown?: (e: React.MouseEvent, node: PipelineNode) => void
  animate?: boolean
  dragging?: boolean
}

export function StageNode({
  node,
  selected,
  dimmed,
  error,
  dropValid,
  onSelect,
  onToggle,
  onConfig,
  draggable,
  onNodeMouseDown,
  animate = true,
  dragging,
}: StageNodeProps) {
  const meta = nodeMeta(node)
  const reserved = NODE_META[node.type].reserved
  const off = node.enabled === false
  const tone = error ? 'var(--destructive)' : meta.tone
  const edge = dropValid
    ? 'var(--success)'
    : selected
      ? 'var(--ring)'
      : error
        ? 'var(--destructive)'
        : 'var(--border)'
  const Icon = pipelineIcon(meta.icon)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation()
        onSelect?.(node.id)
      }}
      onDoubleClick={(e) => {
        e.stopPropagation()
        onConfig?.(node)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onConfig?.(node)
      }}
      onMouseDown={(e) => {
        if (draggable && !reserved) onNodeMouseDown?.(e, node)
      }}
      style={{
        position: 'absolute',
        left: node.ui_x,
        top: node.ui_y,
        width: NODE_W,
        boxSizing: 'border-box',
        display: 'grid',
        gap: 7,
        padding: '8px 9px',
        borderRadius: 'var(--radius-card)',
        cursor:
          draggable && !reserved ? (dragging ? 'grabbing' : 'grab') : 'pointer',
        background: 'var(--card)',
        zIndex: dragging ? 20 : selected ? 8 : 2,
        borderTop: `${reserved ? 2 : 1}px solid ${edge}`,
        borderRight: `${reserved ? 2 : 1}px solid ${edge}`,
        borderBottom: `${reserved ? 2 : 1}px solid ${edge}`,
        borderLeft: `3px solid ${tone}`,
        boxShadow: dropValid
          ? '0 0 0 3px color-mix(in srgb, var(--success) 32%, transparent)'
          : dragging
            ? '0 12px 30px rgba(0,0,0,.5)'
            : selected
              ? '0 0 0 3px color-mix(in srgb, var(--ring) 28%, transparent)'
              : reserved
                ? 'none'
                : '0 1px 0 rgba(0,0,0,.25)',
        opacity: dimmed ? 0.32 : off ? 0.55 : 1,
        transition: `opacity .14s ease, box-shadow .12s ease, border-color .12s ease${
          animate && !dragging
            ? ', left .26s cubic-bezier(.4,0,.2,1), top .26s cubic-bezier(.4,0,.2,1)'
            : ''
        }`,
        outline: 'none',
      }}
    >
      <div className="flex min-w-0 items-center gap-[7px]">
        <Icon size={14} style={{ color: tone, flexShrink: 0 }} />
        <span
          className="min-w-0 flex-1 truncate font-semibold leading-[1.15] text-foreground"
          style={{ fontSize: 12 }}
        >
          {node.label}
        </span>
        {node.pinned && !reserved && (
          <Pin size={10} style={{ color: 'var(--brand)', flexShrink: 0 }} />
        )}
        {reserved ? (
          <span
            title="Reserved stage — always on; can't be moved, disabled, or removed"
            className="inline-flex shrink-0"
          >
            <Lock size={11} className="text-muted-foreground" />
          </span>
        ) : (
          <Switch
            checked={!off}
            onCheckedChange={(v) => onToggle?.(node.id, v)}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            aria-label={`${node.label} enabled`}
            className="h-4 w-7 shrink-0 [&>span]:h-3 [&>span]:w-3 [&>span]:data-[state=checked]:translate-x-3"
          />
        )}
      </div>
      {!reserved && node.source_scope && <ScopeChips scope={node.source_scope} />}
      {node.stat && <NodeCounts stat={node.stat} />}
      <Mono
        className="uppercase tracking-[0.07em] text-muted-foreground"
        style={{ fontSize: 8.5 }}
      >
        {meta.label}
      </Mono>
    </div>
  )
}
