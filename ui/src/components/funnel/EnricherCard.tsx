// EnricherCard — enricher card for the interleaved funnel order.
//
// Displays: order number with up/down reorder buttons, enricher badge with
// source icon + label, depth badge, adds-context chips, records-to-memory
// chips, budget info, source filter, enriched count, and enable/disable switch.

import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Enricher } from '@/lib/types/funnel'
import { SRC_ICON } from '@/lib/funnel-constants'
import { Mono } from '@/components/Mono'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

export interface EnricherCardProps {
  enricher: Enricher
  order: number
  total: number
  reorderable?: boolean
  onToggle: (id: number) => void
  onMove: (id: number, dir: number) => void
  onOpen: (enricher: Enricher) => void
}

export function EnricherCard({
  enricher,
  order,
  total,
  reorderable = false,
  onToggle,
  onMove,
  onOpen,
}: EnricherCardProps) {
  const ChevronUp = getIcon('ChevronUp')
  const ChevronDown = getIcon('ChevronDown')
  const Sparkles = getIcon('Sparkles')
  const ChevronRight = getIcon('ChevronRight')
  const Link = getIcon('Link')
  const srcIconName = SRC_ICON[enricher.type] ?? 'Database'
  const SrcIcon = getIcon(srcIconName)

  const stop = (e: React.MouseEvent) => e.stopPropagation()

  return (
    <Card
      data-testid={`enricher-card-${enricher.id}`}
      style={{
        borderLeft: '3px solid var(--tertiary)',
        cursor: 'pointer',
        opacity: enricher.enabled ? 1 : 0.62,
        transition: 'opacity .12s ease',
      }}
      onClick={() => onOpen(enricher)}
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
            onClick={() => onMove(enricher.id, -1)}
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
            onClick={() => onMove(enricher.id, 1)}
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
                data-testid="enricher-badge"
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
                  color: '#06303f',
                  background: 'var(--tertiary)',
                }}
              >
                {Sparkles && <Sparkles size={11} />}enricher
              </span>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  fontWeight: 600,
                }}
              >
                {SrcIcon && (
                  <SrcIcon
                    size={15}
                    style={{ color: 'var(--brand)' }}
                  />
                )}
                {enricher.label}
              </span>
              <Mono className="text-[11px] text-[var(--muted-foreground)]">
                {enricher.id}
              </Mono>
              <Badge variant="outline">{enricher.depth}</Badge>
            </div>
            <div onClick={stop}>
              <Switch
                aria-label={`Toggle ${enricher.id}`}
                checked={enricher.enabled}
                onCheckedChange={() => onToggle(enricher.id)}
              />
            </div>
          </div>

          {/* metadata grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr',
              gap: '8px 16px',
              alignItems: 'start',
            }}
          >
            <span
              className="label-mono"
              style={{ fontSize: 10, paddingTop: 2 }}
            >
              Adds context
            </span>
            <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {enricher.adds.map((f) => (
                <span
                  key={f}
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    padding: '1px 7px',
                    borderRadius: 'var(--radius-chip, 2px)',
                    background:
                      'color-mix(in srgb, var(--tertiary) 14%, transparent)',
                    color: 'var(--tertiary)',
                  }}
                >
                  {f}
                </span>
              ))}
            </span>

            <span
              className="label-mono"
              style={{ fontSize: 10, paddingTop: 2 }}
            >
              Records to memory
            </span>
            <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {enricher.records.map((e) => (
                <span
                  key={e}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    padding: '1px 7px',
                    borderRadius: 'var(--radius-chip, 2px)',
                    border: '1px solid var(--border)',
                    color: 'var(--muted-foreground)',
                  }}
                >
                  {Link && <Link size={10} />}
                  {e}
                </span>
              ))}
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--muted-foreground)',
                  alignSelf: 'center',
                }}
              >
                → Knowledge
              </span>
            </span>

            <span
              className="label-mono"
              style={{ fontSize: 10, paddingTop: 2 }}
            >
              Budget
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--muted-foreground)',
              }}
            >
              {enricher.budget.max_calls === 0
                ? 'no external calls'
                : `≤ ${enricher.budget.max_calls} call/item`}{' '}
              · {enricher.budget.max_time_ms / 1000}s · avg{' '}
              {enricher.avg_ms}ms
            </span>
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
              applies to{' '}
              <span style={{ color: 'var(--foreground)' }}>
                {enricher.type}
              </span>{' '}
              items
            </span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--tertiary)',
              }}
            >
              <Mono>{enricher.enriched}</Mono> enriched{' '}
              {ChevronRight && <ChevronRight size={13} />}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
