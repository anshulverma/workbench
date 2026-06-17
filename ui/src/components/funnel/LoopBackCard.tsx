// LoopBackCard — loop-back stage card for the interleaved funnel order.
//
// Displays: order number with up/down reorder buttons, loop-back badge with
// label, max-loops badge, trigger description, re-inject target, condition,
// guard info, stats (looped count + avg loops), and enable/disable switch.

import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { LoopBack } from '@/lib/types/funnel'
import { Mono } from '@/components/Mono'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

export interface LoopBackCardProps {
  lb: LoopBack
  order: number
  total: number
  reorderable?: boolean
  onToggle: (id: number) => void
  onMove: (id: number, dir: number) => void
}

export function LoopBackCard({
  lb,
  order,
  total,
  reorderable = false,
  onToggle,
  onMove,
}: LoopBackCardProps) {
  const ChevronUp = getIcon('ChevronUp')
  const ChevronDown = getIcon('ChevronDown')
  const RotateCcw = getIcon('RotateCcw')
  const CornerLeftUp = getIcon('CornerLeftUp')

  const stop = (e: React.MouseEvent) => e.stopPropagation()

  return (
    <Card
      data-testid={`loopback-card-${lb.id}`}
      style={{
        borderLeft: '3px solid var(--primary)',
        opacity: lb.enabled ? 1 : 0.62,
        transition: 'opacity .12s ease',
      }}
    >
      <CardContent className="flex items-stretch p-0">
        {/* reorder rail */}
        <div
          onClick={stop}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            padding: '0 10px',
            borderRight: '1px solid var(--border)',
            background: 'var(--surface-lowest)',
          }}
        >
          <button
            className="wb-iconbtn"
            style={{
              width: 22,
              height: 18,
              opacity: reorderable && order > 0 ? 1 : 0.25,
            }}
            aria-label="Move up"
            disabled={!reorderable || order === 0}
            onClick={() => onMove(lb.id, -1)}
          >
            {ChevronUp && <ChevronUp size={14} />}
          </button>
          <Mono className="text-xs font-bold">
            {String(order + 1).padStart(2, '0')}
          </Mono>
          <button
            className="wb-iconbtn"
            style={{
              width: 22,
              height: 18,
              opacity: reorderable && order < total - 1 ? 1 : 0.25,
            }}
            aria-label="Move down"
            disabled={!reorderable || order === total - 1}
            onClick={() => onMove(lb.id, 1)}
          >
            {ChevronDown && <ChevronDown size={14} />}
          </button>
        </div>

        {/* card body */}
        <div
          style={{
            flex: 1,
            padding: 16,
            display: 'grid',
            gap: 12,
            minWidth: 0,
          }}
        >
          {/* top row */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 12,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              <span
                data-testid="loopback-badge"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '1px 8px',
                  borderRadius: 'var(--radius-chip, 2px)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                  color: '#0e0e11',
                  background: 'var(--brand)',
                }}
              >
                {RotateCcw && <RotateCcw size={11} />}loop-back
              </span>
              <span style={{ fontWeight: 600 }}>{lb.label}</span>
              <Mono className="text-[11px] text-[var(--muted-foreground)]">
                {lb.id}
              </Mono>
              <Badge variant="outline">max {lb.max_loops}×</Badge>
            </div>
            <div onClick={stop}>
              <Switch
                aria-label={`Toggle ${lb.id}`}
                checked={lb.enabled}
                onCheckedChange={() => onToggle(lb.id)}
              />
            </div>
          </div>

          {/* trigger */}
          <p
            style={{
              margin: 0,
              fontSize: 13,
              lineHeight: 1.5,
              color: 'var(--foreground)',
            }}
          >
            {lb.trigger}
          </p>

          {/* metadata grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr',
              gap: '8px 16px',
              alignItems: 'center',
            }}
          >
            <span className="label-mono" style={{ fontSize: 10 }}>
              Re-injects to
            </span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--brand)',
              }}
            >
              {CornerLeftUp && <CornerLeftUp size={13} />}top of funnel —
              re-enriched + re-filtered
            </span>

            <span className="label-mono" style={{ fontSize: 10 }}>
              Condition
            </span>
            <Mono className="text-xs text-[var(--muted-foreground)]">
              {lb.condition}
            </Mono>
          </div>

          {/* footer */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--muted-foreground)',
              }}
            >
              guard: stops after{' '}
              <span style={{ color: 'var(--foreground)' }}>
                {lb.max_loops}
              </span>{' '}
              loops
            </span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--brand)',
              }}
            >
              <Mono>{lb.looped}</Mono> looped · avg {lb.avg_loops}×
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
