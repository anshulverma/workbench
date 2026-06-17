import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { FunnelItem } from '@/lib/types/funnel'
import type { SearchItem } from '@/lib/types/search'
import { SRC_ICON } from '@/lib/funnel-constants'
import { itemLog, stageTimings, ruleById } from '@/lib/funnel-helpers'
import { ActionChip } from '@/components/ActionChip'
import { VerdictPill } from '@/components/VerdictPill'
import { Mono } from '@/components/Mono'
import { Portal } from '@/components/Portal'
import { FunnelStage } from '@/components/funnel/FunnelStage'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = now - then
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/**
 * ItemFunnelDialog -- full item provenance modal.
 *
 * Shows the item's source, ID, timestamp, title, VerdictPill, the complete
 * treatment log (all stages via FunnelStage components with timings), and
 * an aggregated verdict card with contributing signals + merged outcome.
 *
 * Canonical mounting pattern: the page holds useState<string|null>(null),
 * click calls the setter, dialog rendered at page root with
 * open={!!id} onClose={() => setId(null)}.
 */
export function ItemFunnelDialog({
  item,
  open,
  onClose,
  filterRules = [],
  enrichers = [],
  enrichmentSamples,
}: {
  item: FunnelItem | SearchItem | null
  open: boolean
  onClose: () => void
  filterRules?: Array<{ id: number; prompt: string }>
  enrichers?: Array<{ id: number; label: string }>
  enrichmentSamples?: Record<
    string,
    Array<{ id: number; context: Record<string, string | number | boolean> }>
  >
}) {
  if (!open || !item) return null

  const funnelItem: FunnelItem = {
    id: item.id,
    summary: item.summary,
    source: item.source,
    created_at: item.created_at,
    stages: item.stages,
    verdict: item.verdict,
  }

  const log = itemLog(
    funnelItem,
    enrichers as Parameters<typeof itemLog>[1],
    enrichmentSamples,
  )
  const tm = stageTimings(log)
  const base = item.created_at ? new Date(item.created_at).getTime() : null

  const enricherCount = log.filter((s) =>
    String(s.filterId).startsWith('en_'),
  ).length
  const filterCount = log.length - enricherCount
  const totalMs = tm.length ? tm[tm.length - 1].at + tm[tm.length - 1].dur : 0

  const signals = (item.stages ?? []).filter(
    (s) =>
      ['drop', 'include', 'label'].includes(s.outcome) &&
      typeof s.confidence === 'number',
  )
  const contexts = (item.stages ?? []).filter((s) => s.context)

  const srcIconName = SRC_ICON[item.source] ?? 'Database'
  const SrcIcon = getIcon(srcIconName)
  const XIcon = getIcon('X')
  const SparklesIcon = getIcon('Sparkles')
  const CornerIcon = getIcon('CornerDownRight')

  return (
    <Portal>
      <div
        data-testid="funnel-dialog-overlay"
        className="wb-overlay"
        style={{ alignItems: 'center', paddingTop: 0, zIndex: 120 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
      >
        <div
          className="wb-dialog-card"
          role="dialog"
          aria-modal="true"
          data-testid="funnel-dialog"
          style={{
            width: 'min(640px, 94vw)',
            padding: 0,
            overflow: 'hidden',
            maxHeight: '88vh',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* header */}
          <div
            style={{
              padding: '18px 20px',
              borderBottom: '1px solid var(--border)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 10,
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  color: 'var(--muted-foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                {SrcIcon && <SrcIcon size={13} />}
                {item.source}
              </span>
              <Mono className="text-[11px] text-[var(--muted-foreground)]">
                {item.id}
              </Mono>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--muted-foreground)',
                }}
              >
                · {relativeTime(item.created_at)}
              </span>
              <button
                className="wb-iconbtn"
                style={{ marginLeft: 'auto', width: 28, height: 28 }}
                aria-label="Close"
                onClick={onClose}
              >
                {XIcon && <XIcon size={16} />}
              </button>
            </div>

            <h2
              data-testid="dialog-title"
              className="wb-h2"
              style={{
                fontSize: 17,
                marginBottom: 10,
                display: 'flex',
                alignItems: 'baseline',
                gap: 10,
                flexWrap: 'wrap',
              }}
            >
              <Mono className="text-[15px] font-bold text-[var(--tertiary)]">
                {item.id}
              </Mono>
              <span>{item.summary}</span>
            </h2>

            <VerdictPill verdict={item.verdict} large />
          </div>

          {/* funnel trace */}
          <div style={{ padding: '18px 20px', overflowY: 'auto' }}>
            <h3
              className="wb-section-h"
              style={{ marginBottom: 14 }}
              data-testid="treatment-log-header"
            >
              Treatment log · {enricherCount} enricher
              {enricherCount === 1 ? '' : 's'} + {filterCount} filter
              {filterCount === 1 ? '' : 's'} · {totalMs}ms total
            </h3>

            {log.map((s, i) => (
              <FunnelStage
                key={i}
                stage={s}
                index={i}
                isLast={i === log.length - 1}
                item={funnelItem}
                editable={!String(s.filterId).startsWith('en_')}
                timing={tm[i]}
                baseTime={base}
                filterRules={filterRules}
                enrichers={enrichers}
              />
            ))}

            {/* aggregated verdict */}
            <div
              data-testid="aggregated-verdict"
              style={{
                marginTop: 8,
                padding: 16,
                borderRadius: 'var(--radius-card, 6px)',
                border:
                  '1px solid color-mix(in srgb, var(--primary) 35%, var(--border))',
                background:
                  'color-mix(in srgb, var(--primary) 7%, var(--card))',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                {SparklesIcon && (
                  <SparklesIcon
                    size={15}
                    style={{ color: 'var(--brand)' }}
                  />
                )}
                <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
                  Aggregated verdict
                </h3>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '.06em',
                    color: 'var(--brand)',
                    border:
                      '1px solid color-mix(in srgb, var(--primary) 40%, transparent)',
                    borderRadius: 'var(--radius-chip, 2px)',
                    padding: '1px 6px',
                  }}
                >
                  LLM joined
                </span>
              </div>

              {signals.length > 0 && (
                <div style={{ display: 'grid', gap: 6, marginBottom: 12 }}>
                  {signals.map((s, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}
                    >
                      <ActionChip
                        action={s.outcome}
                        label={s.label}
                        confidence={s.confidence}
                        small
                      />
                      <span
                        style={{
                          fontSize: 12,
                          color: 'var(--muted-foreground)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {s.context ||
                          ruleById(s.filterId, filterRules, enrichers).prompt}
                      </span>
                    </div>
                  ))}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      paddingTop: 8,
                      borderTop:
                        '1px solid color-mix(in srgb, var(--primary) 25%, var(--border))',
                    }}
                  >
                    {CornerIcon && (
                      <CornerIcon
                        size={14}
                        style={{ color: 'var(--muted-foreground)' }}
                      />
                    )}
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        color: 'var(--muted-foreground)',
                      }}
                    >
                      merged →
                    </span>
                    <VerdictPill verdict={item.verdict} />
                  </div>
                </div>
              )}

              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55 }}>
                {item.verdict.rationale}
              </p>

              {contexts.length > 0 && (
                <p
                  style={{
                    margin: '10px 0 0',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--muted-foreground)',
                  }}
                >
                  // carried forward:{' '}
                  {contexts.map((c) => c.context).join(' · ')}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </Portal>
  )
}
