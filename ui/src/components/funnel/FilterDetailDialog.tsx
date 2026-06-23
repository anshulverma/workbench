// FilterDetailDialog — shows items processed by a filter, corrections summary.
//
// Opens as a modal overlay showing the filter's action chip, ID, tuned prompt,
// recent items touched by this rule, and a corrections summary section where
// user overrides appear. Click any item row to open its ItemFunnelDialog.

import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { FilterRuleExtended, FunnelItem, StageOutcome } from '@/lib/types/funnel'
import { SRC_ICON } from '@/lib/funnel-constants'
import { ActionChip } from '@/components/ActionChip'
import { VerdictPill } from '@/components/VerdictPill'
import { Mono } from '@/components/Mono'
import { Portal } from '@/components/Portal'
import { useCorrections } from '@/hooks/useFeedback'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

export interface FilterDetailDialogProps {
  rule: FilterRuleExtended | null
  items: FunnelItem[]
  onOpenItem: (item: FunnelItem) => void
  onClose: () => void
}

export function FilterDetailDialog({
  rule,
  items,
  onOpenItem,
  onClose,
}: FilterDetailDialogProps) {
  const correctionsQ = useCorrections()
  const XIcon = getIcon('X')
  const WarnIcon = getIcon('MessageSquareWarning')
  const ArrowRight = getIcon('ArrowRight')
  const ChevronRight = getIcon('ChevronRight')

  if (!rule) return null

  const matchingItems = items.filter((it) =>
    it.stages.some((s) => s.filterId === String(rule.id)),
  )
  const allCorrections = correctionsQ.data ?? []
  const corrections = allCorrections.filter((c) => c.filter_id === String(rule.id))

  return (
    <Portal>
      <div
        className="wb-overlay"
        data-testid="filter-detail-overlay"
        style={{ alignItems: 'center', paddingTop: 0, zIndex: 105 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
      >
        <div
          className="wb-dialog-card"
          role="dialog"
          aria-modal="true"
          data-testid="filter-detail-dialog"
          style={{
            width: 'min(700px, 94vw)',
            padding: 0,
            overflow: 'hidden',
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
                marginBottom: 8,
              }}
            >
              <ActionChip action={rule.action} label={rule.label} />
              <Mono className="text-[11px] text-[var(--muted-foreground)]">
                {rule.id}
              </Mono>
              <button
                className="wb-iconbtn"
                style={{ marginLeft: 'auto', width: 28, height: 28 }}
                aria-label="Close"
                onClick={onClose}
              >
                {XIcon && <XIcon size={16} />}
              </button>
            </div>
            <p style={{ margin: 0, fontSize: 15, lineHeight: 1.45 }}>
              "{rule.prompt}"
            </p>
            <p
              style={{
                margin: '8px 0 0',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--muted-foreground)',
              }}
            >
              {matchingItems.length} recent item
              {matchingItems.length === 1 ? '' : 's'} touched · click any item
              to see its full funnel trace
            </p>

            {/* corrections summary */}
            {corrections.length > 0 && (
              <div
                data-testid="corrections-summary"
                style={{
                  marginTop: 12,
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-control, 4px)',
                  border:
                    '1px solid color-mix(in srgb, var(--primary) 40%, transparent)',
                  background:
                    'color-mix(in srgb, var(--primary) 8%, transparent)',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  {WarnIcon && (
                    <WarnIcon
                      size={14}
                      style={{ color: 'var(--brand)' }}
                    />
                  )}
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    You changed this filter's classification on{' '}
                    {corrections.length} item
                    {corrections.length === 1 ? '' : 's'}
                  </span>
                </div>
                <div
                  style={{ display: 'grid', gap: 4, marginTop: 8 }}
                >
                  {corrections.map((c) => (
                    <div
                      key={c.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        fontSize: 12,
                      }}
                    >
                      <span
                        style={{
                          color: 'var(--muted-foreground)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          maxWidth: 260,
                        }}
                      >
                        {c.item_summary}
                      </span>
                      <span
                        style={{
                          marginLeft: 'auto',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <ActionChip
                          action={c.original_action as StageOutcome}
                          label={c.from_label ?? undefined}
                          small
                        />
                        {ArrowRight && (
                          <ArrowRight
                            size={11}
                            style={{ color: 'var(--muted-foreground)' }}
                          />
                        )}
                        <ActionChip
                          action={c.corrected_action as StageOutcome}
                          label={c.to_label ?? undefined}
                          small
                        />
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* items table */}
          <div style={{ maxHeight: '54vh', overflowY: 'auto' }}>
            {matchingItems.length === 0 ? (
              <p
                style={{
                  padding: 24,
                  textAlign: 'center',
                  color: 'var(--muted-foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                // no items processed by this rule in the window
              </p>
            ) : (
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: 13,
                }}
              >
                <thead>
                  <tr>
                    {[
                      'Item ID',
                      'Item',
                      'Source',
                      'This rule did',
                      'Final verdict',
                      '',
                    ].map((hd, i) => (
                      <th
                        key={i}
                        style={{
                          textAlign: 'left',
                          padding: '8px 16px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 10,
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '.06em',
                          color: 'var(--muted-foreground)',
                          background: 'var(--surface-high)',
                          position: 'sticky',
                          top: 0,
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        {hd}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matchingItems.map((it) => {
                    const stage = it.stages.find(
                      (s) => s.filterId === String(rule.id),
                    )
                    const corrected = allCorrections.find(
                      (c) => c.item_id === it.id && c.filter_id === String(rule.id),
                    )
                    const srcIconName = SRC_ICON[it.source] ?? 'Database'
                    const SrcIcon = getIcon(srcIconName)

                    return (
                      <tr
                        key={it.id}
                        onClick={() => onOpenItem(it)}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          cursor: 'pointer',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = 'var(--accent)'
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'transparent'
                        }}
                      >
                        <td style={{ padding: '9px 16px' }}>
                          <Mono className="text-xs text-[var(--tertiary)]">
                            {it.id}
                          </Mono>
                        </td>
                        <td
                          style={{
                            padding: '9px 16px',
                            maxWidth: 240,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {it.summary}
                        </td>
                        <td style={{ padding: '9px 16px' }}>
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
                            {SrcIcon && <SrcIcon size={12} />}
                            {it.source}
                          </span>
                        </td>
                        <td style={{ padding: '9px 16px' }}>
                          {corrected ? (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 5,
                              }}
                            >
                              <ActionChip
                                action={corrected.corrected_action as StageOutcome}
                                label={corrected.to_label ?? undefined}
                                small
                              />
                              <span
                                style={{
                                  fontFamily: 'var(--font-mono)',
                                  fontSize: 10,
                                  color: 'var(--brand)',
                                }}
                              >
                                corrected
                              </span>
                            </span>
                          ) : stage ? (
                            <ActionChip
                              action={stage.outcome}
                              label={stage.label}
                              confidence={stage.confidence}
                              small
                            />
                          ) : null}
                        </td>
                        <td style={{ padding: '9px 16px' }}>
                          <VerdictPill verdict={it.verdict} />
                        </td>
                        <td
                          style={{
                            padding: '9px 16px',
                            textAlign: 'right',
                          }}
                        >
                          {ChevronRight && (
                            <ChevronRight
                              size={15}
                              style={{ color: 'var(--muted-foreground)' }}
                            />
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </Portal>
  )
}
