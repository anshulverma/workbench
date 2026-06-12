// FilterRuleCard — reorderable filter card for the interleaved funnel order.
//
// Displays: order number with up/down reorder buttons, action chip, rule ID,
// tuned badge, kebab menu with dropdown actions, enable/disable switch,
// natural-language prompt (quoted), source chips, confidence bar, origin badge,
// and processed-items count.

import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { FilterRuleExtended } from '@/lib/types/funnel'
import { ACTION_META } from '@/lib/funnel-constants'
import { ActionChip } from '@/components/ActionChip'
import { SourceChip } from '@/components/SourceChip'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { Mono } from '@/components/Mono'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

export interface FilterRuleCardProps {
  rule: FilterRuleExtended
  order: number
  total: number
  reorderable?: boolean
  onToggle: (id: string) => void
  onDelete: (id: string) => void
  onMove: (id: string, dir: number) => void
  onOpen: (rule: FilterRuleExtended) => void
}

export function FilterRuleCard({
  rule,
  order,
  total,
  reorderable = false,
  onToggle,
  onDelete,
  onMove,
  onOpen,
}: FilterRuleCardProps) {
  const m = ACTION_META[rule.action] ?? ACTION_META.drop
  const ChevronUp = getIcon('ChevronUp')
  const ChevronDown = getIcon('ChevronDown')
  const EllipsisVertical = getIcon('EllipsisVertical')
  const Sparkles = getIcon('Sparkles')
  const ChevronRight = getIcon('ChevronRight')

  const stop = (e: React.MouseEvent) => e.stopPropagation()

  return (
    <Card
      data-testid={`filter-rule-card-${rule.id}`}
      style={{
        borderLeft: `3px solid ${m.accent}`,
        cursor: 'pointer',
        opacity: rule.enabled ? 1 : 0.62,
        transition: 'opacity .12s ease',
      }}
      onClick={() => onOpen(rule)}
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
            onClick={() => onMove(rule.id, -1)}
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
            onClick={() => onMove(rule.id, 1)}
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
          {/* top row: action chip, id, tuned, kebab, switch */}
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
              <ActionChip action={rule.action} label={rule.label} />
              <Mono className="text-[11px] text-[var(--muted-foreground)]">
                {rule.id}
              </Mono>
              {rule.tuned && Sparkles && (
                <span
                  data-testid="tuned-badge"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                    color: 'var(--success)',
                  }}
                >
                  <Sparkles size={11} />
                  tuned
                </span>
              )}
            </div>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              onClick={stop}
            >
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="wb-iconbtn"
                    style={{ width: 28, height: 28 }}
                    aria-label={`Actions for ${rule.id}`}
                  >
                    {EllipsisVertical && <EllipsisVertical size={16} />}
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onOpen(rule)}>
                    View processed items
                  </DropdownMenuItem>
                  <DropdownMenuItem>Edit prompt</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onToggle(rule.id)}>
                    {rule.enabled ? 'Disable' : 'Enable'}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive"
                    onSelect={() => onDelete(rule.id)}
                  >
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Switch
                aria-label={`Toggle ${rule.id}`}
                checked={rule.enabled}
                onCheckedChange={() => onToggle(rule.id)}
              />
            </div>
          </div>

          {/* prompt */}
          <p
            style={{
              margin: 0,
              fontSize: 14,
              lineHeight: 1.5,
              color: rule.enabled
                ? 'var(--foreground)'
                : 'var(--muted-foreground)',
            }}
          >
            <span
              style={{
                color: 'var(--muted-foreground)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              "
            </span>
            {rule.prompt}
            <span
              style={{
                color: 'var(--muted-foreground)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              "
            </span>
          </p>

          {/* metadata grid: applies-to + confidence */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr',
              gap: '8px 16px',
              alignItems: 'center',
            }}
          >
            <span className="label-mono" style={{ fontSize: 10 }}>
              Applies to
            </span>
            <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {rule.sources.length === 4 ? (
                <SourceChip name="all sources" />
              ) : (
                rule.sources.map((s) => <SourceChip key={s} name={s} />)
              )}
            </span>
            <span className="label-mono" style={{ fontSize: 10 }}>
              {rule.action === 'context' ? 'Effect' : 'Confidence'}
            </span>
            {typeof rule.confidence === 'number' ? (
              <ConfidenceBar value={rule.confidence} />
            ) : (
              <span
                style={{
                  fontSize: 12,
                  color: 'var(--muted-foreground)',
                  fontStyle: 'italic',
                }}
              >
                enriches — no score, never decides
              </span>
            )}
          </div>

          {/* footer: origin + processed count */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Badge variant="outline">{rule.origin}</Badge>
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
              <Mono>{rule.matched}</Mono> processed{' '}
              {ChevronRight && <ChevronRight size={13} />}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
