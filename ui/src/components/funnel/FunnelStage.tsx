import { useState } from 'react'
import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { FunnelStage as FunnelStageType, FunnelItem } from '@/lib/types/funnel'
import type { TimingInfo } from '@/lib/funnel-helpers'
import { ruleById } from '@/lib/funnel-helpers'
import { STAGE_META } from '@/lib/funnel-constants'
import { ActionChip } from '@/components/ActionChip'
import { Mono } from '@/components/Mono'
import { Button } from '@/components/ui/button'
import { useFeedbackStore } from '@/hooks/useFeedback'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

const CORRECTION_CHOICES: Array<[string, string]> = [
  ['include', 'Keep / include'],
  ['drop', 'Drop'],
  ['label', 'Label spam'],
  ['pass', 'No action'],
]

/**
 * FunnelStage — vertical timeline stepper for a single filter/enricher stage.
 *
 * Shows a colored circle with icon, connecting line, stage header with
 * order number + filterId + enricher badge + ActionChip, optional timing,
 * correction picker when editable, and feedback receipt when override exists.
 */
export function FunnelStage({
  stage,
  index,
  isLast,
  item,
  editable,
  timing,
  baseTime,
  filterRules = [],
  enrichers = [],
}: {
  stage: FunnelStageType
  index: number
  isLast: boolean
  item?: FunnelItem | null
  editable?: boolean
  timing?: TimingInfo | null
  baseTime?: number | null
  filterRules?: Array<{ id: number; prompt: string }>
  enrichers?: Array<{ id: number; label: string }>
}) {
  const fb = useFeedbackStore()
  const [editing, setEditing] = useState(false)

  const ov = editable && item ? fb.overrideFor(String(item.id), stage.filterId) : null
  // The override and its filter-tuning task are 1:1 (same item+filter); find the
  // open task so the receipt can link straight to it on the Actions page.
  const tuningTask =
    ov && item
      ? fb
          .openTasks()
          .find(
            (t) => t.itemId === String(item.id) && t.filterId === stage.filterId,
          ) ?? null
      : null
  const effOutcome = ov ? ov.toOutcome : stage.outcome
  const effLabel = ov ? ov.toLabel : stage.label
  const m = STAGE_META[effOutcome] ?? STAGE_META.pass
  const rule = ruleById(stage.filterId, filterRules, enrichers)
  const muted = effOutcome === 'pass' || effOutcome === 'skip'
  const isEnricher = String(stage.filterId).startsWith('en_')

  const CircleIcon = getIcon(m.icon)
  const ClockIcon = getIcon('Clock')
  const ArrowIcon = getIcon('ArrowRight')
  const SparklesIcon = getIcon('Sparkles')
  const PlusIcon = getIcon('Plus')
  const PencilIcon = getIcon('PencilLine')
  const UndoIcon = getIcon('Undo2')
  const WarnIcon = getIcon('MessageSquareWarning')

  const apply = (to: string) => {
    if (!item) return
    fb.addOverride({
      itemId: String(item.id),
      itemSummary: item.summary,
      filterId: stage.filterId,
      filterPrompt: rule.prompt,
      fromOutcome: stage.outcome,
      fromLabel: stage.label,
      toOutcome: to as FunnelStageType['outcome'],
      toLabel: to === 'label' ? 'spam' : undefined,
    })
    setEditing(false)
  }

  return (
    <div
      data-testid="funnel-stage"
      data-stage-index={index}
      style={{ display: 'grid', gridTemplateColumns: '28px 1fr', gap: 12 }}
    >
      {/* rail */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <span
          data-testid="stage-circle"
          style={{
            width: 26,
            height: 26,
            borderRadius: 9999,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            background: muted ? 'var(--surface-high)' : m.accent,
            color: muted
              ? 'var(--muted-foreground)'
              : effOutcome === 'drop'
                ? '#ffb4ab'
                : '#0e0e11',
            border: muted
              ? '1px solid var(--border)'
              : ov
                ? '2px solid var(--brand)'
                : 'none',
          }}
        >
          {CircleIcon && <CircleIcon size={13} />}
        </span>
        {!isLast && (
          <span
            data-testid="connecting-line"
            style={{ flex: 1, width: 2, background: 'var(--border)', minHeight: 16 }}
          />
        )}
      </div>

      {/* body */}
      <div style={{ paddingBottom: isLast ? 0 : 16, opacity: muted && !ov ? 0.72 : 1 }}>
        {/* header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Mono className="text-[11px] text-[var(--muted-foreground)]">
            {String(index + 1).padStart(2, '0')} · {stage.filterId}
          </Mono>

          {isEnricher && (
            <span
              data-testid="enricher-badge"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '.06em',
                color: '#06303f',
                background: 'var(--tertiary)',
                borderRadius: 'var(--radius-chip, 2px)',
                padding: '1px 5px',
              }}
            >
              {SparklesIcon && <SparklesIcon size={9} />}enricher
            </span>
          )}

          {ov ? (
            <span
              data-testid="override-display"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <span style={{ textDecoration: 'line-through', opacity: 0.6 }}>
                <ActionChip action={stage.outcome} label={stage.label} small />
              </span>
              {ArrowIcon && (
                <ArrowIcon size={12} style={{ color: 'var(--muted-foreground)' }} />
              )}
              <ActionChip action={effOutcome} label={effLabel} small />
            </span>
          ) : (
            <ActionChip
              action={stage.outcome}
              label={stage.label}
              confidence={stage.confidence}
              small
            />
          )}

          {stage.weak && !ov && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--brand)',
              }}
            >
              weak · below threshold
            </span>
          )}

          {timing && (
            <span
              data-testid="timing-info"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--muted-foreground)',
              }}
            >
              {ClockIcon && <ClockIcon size={10} />}
              {baseTime
                ? `${new Date(baseTime + timing.at).toLocaleTimeString([], { hour12: false })} +${timing.at}ms`
                : `+${timing.at}ms`}
              <span style={{ color: 'var(--tertiary)' }}>· {timing.dur}ms</span>
            </span>
          )}

          {/* correct / undo button */}
          {editable && item && !isEnricher && !editing && (
            <button
              data-testid={ov ? 'undo-button' : 'correct-button'}
              onClick={() =>
                ov
                  ? fb.removeOverride(String(item.id), stage.filterId)
                  : setEditing(true)
              }
              style={{
                marginLeft: 'auto',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                background: 'none',
                border: 0,
                cursor: 'pointer',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: ov ? 'var(--tertiary)' : 'var(--muted-foreground)',
              }}
            >
              {ov
                ? UndoIcon && <UndoIcon size={12} />
                : PencilIcon && <PencilIcon size={12} />}
              {ov ? 'undo' : 'correct'}
            </button>
          )}
        </div>

        {/* prompt */}
        <p
          style={{
            margin: '6px 0 0',
            fontSize: 13,
            color: 'var(--muted-foreground)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          "{fb.promptFor(stage.filterId, rule.prompt)}"
        </p>

        {/* reason */}
        {stage.reason && (
          <p style={{ margin: '6px 0 0', fontSize: 13, lineHeight: 1.5 }}>
            {stage.reason}
          </p>
        )}

        {/* context badge */}
        {stage.context && (
          <div
            data-testid="context-badge"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              marginTop: 8,
              padding: '4px 10px',
              borderRadius: 'var(--radius-control, 4px)',
              background:
                'color-mix(in srgb, var(--tertiary) 14%, transparent)',
              border:
                '1px solid color-mix(in srgb, var(--tertiary) 40%, transparent)',
            }}
          >
            {PlusIcon && (
              <PlusIcon size={12} style={{ color: 'var(--tertiary)' }} />
            )}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--tertiary)',
              }}
            >
              {stage.context}
            </span>
          </div>
        )}

        {/* correction picker */}
        {editing && (
          <div
            data-testid="correction-picker"
            style={{
              marginTop: 10,
              padding: 12,
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-card, 6px)',
              background: 'var(--surface-lowest)',
              display: 'grid',
              gap: 8,
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--muted-foreground)',
              }}
            >
              This should have been...
            </span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {CORRECTION_CHOICES.filter(([c]) => c !== stage.outcome).map(
                ([c, lbl]) => (
                  <Button
                    key={c}
                    size="sm"
                    variant="outline"
                    onClick={() => apply(c)}
                  >
                    {lbl}
                  </Button>
                ),
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* feedback receipt */}
        {ov && (
          <div
            data-testid="feedback-receipt"
            style={{
              marginTop: 10,
              padding: 12,
              borderRadius: 'var(--radius-card, 6px)',
              border:
                '1px solid color-mix(in srgb, var(--primary) 35%, var(--border))',
              background:
                'color-mix(in srgb, var(--primary) 7%, var(--card))',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {WarnIcon && (
                <WarnIcon size={14} style={{ color: 'var(--brand)' }} />
              )}
              <span style={{ fontSize: 13, fontWeight: 600 }}>
                You changed this filter's classification
              </span>
            </div>
            <p
              style={{
                margin: '6px 0 0',
                fontSize: 13,
                lineHeight: 1.5,
                color: 'var(--muted-foreground)',
              }}
            >
              Sent to{' '}
              <Mono className="text-xs">{stage.filterId}</Mono> as a
              negative example. A filter-tuning task was created to update its
              prompt so it handles cases like this next time.
            </p>
            {tuningTask && (
              <a
                href={`#/actions?tuning=${tuningTask.id}`}
                style={{
                  display: 'inline-block',
                  marginTop: 8,
                  fontSize: 12,
                  color: 'var(--brand)',
                }}
                className="hover:underline"
              >
                View the filter-tuning task →
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
