// EnricherDetailDialog — shows enrichment samples with context dicts.
//
// Opens as a modal overlay displaying the enricher label, ID, depth info,
// and a list of recently enriched items with their resolved context key-value
// pairs and recorded entities.

import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Enricher, EnrichmentSample } from '@/lib/types/funnel'
import { SRC_ICON } from '@/lib/funnel-constants'
import { Mono } from '@/components/Mono'
import { Portal } from '@/components/Portal'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

export interface EnricherDetailDialogProps {
  enricher: Enricher | null
  samples: EnrichmentSample[]
  onClose: () => void
}

export function EnricherDetailDialog({
  enricher,
  samples,
  onClose,
}: EnricherDetailDialogProps) {
  const XIcon = getIcon('X')
  const Sparkles = getIcon('Sparkles')
  const LinkIcon = getIcon('Link')

  if (!enricher) return null

  const srcIconName = SRC_ICON[enricher.type] ?? 'Database'
  const SrcIcon = getIcon(srcIconName)

  return (
    <Portal>
      <div
        className="wb-overlay"
        data-testid="enricher-detail-overlay"
        style={{ alignItems: 'center', paddingTop: 0, zIndex: 105 }}
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
      >
        <div
          className="wb-dialog-card"
          role="dialog"
          aria-modal="true"
          data-testid="enricher-detail-dialog"
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
              <span
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
              <button
                className="wb-iconbtn"
                style={{ marginLeft: 'auto', width: 28, height: 28 }}
                aria-label="Close"
                onClick={onClose}
              >
                {XIcon && <XIcon size={16} />}
              </button>
            </div>
            <p
              style={{
                margin: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--muted-foreground)',
              }}
            >
              {enricher.enriched} {enricher.type} items enriched · adds{' '}
              {enricher.adds.length} context fields · records{' '}
              {enricher.records.join(' + ')} to memory
            </p>
          </div>

          {/* samples list */}
          <div
            style={{
              maxHeight: '56vh',
              overflowY: 'auto',
              padding: 16,
              display: 'grid',
              gap: 12,
            }}
          >
            {samples.length === 0 ? (
              <p
                style={{
                  textAlign: 'center',
                  color: 'var(--muted-foreground)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                // no recent enrichments in the window
              </p>
            ) : (
              samples.map((s) => (
                <div
                  key={s.id}
                  data-testid={`enrichment-sample-${s.id}`}
                  style={{
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-card, 6px)',
                    padding: 14,
                    display: 'grid',
                    gap: 10,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <Mono className="text-[11px] text-[var(--muted-foreground)]">
                      {s.id}
                    </Mono>
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {s.summary}
                    </span>
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      gap: 6,
                      flexWrap: 'wrap',
                    }}
                  >
                    {Object.entries(s.context).map(([k, v]) => (
                      <span
                        key={k}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 5,
                          fontFamily: 'var(--font-mono)',
                          fontSize: 12,
                          padding: '2px 8px',
                          borderRadius: 'var(--radius-chip, 2px)',
                          background: 'var(--surface-lowest)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        <span style={{ color: 'var(--brand)' }}>{k}</span>
                        <span style={{ color: 'var(--muted-foreground)' }}>
                          :
                        </span>
                        <span style={{ color: 'var(--tertiary)' }}>
                          {String(v)}
                        </span>
                      </span>
                    ))}
                  </div>

                  {s.entities && s.entities.length > 0 && (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        flexWrap: 'wrap',
                        paddingTop: 4,
                        borderTop: '1px solid var(--border)',
                      }}
                    >
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 10,
                          textTransform: 'uppercase',
                          letterSpacing: '.06em',
                          color: 'var(--muted-foreground)',
                        }}
                      >
                        recorded
                      </span>
                      {s.entities.map((e) => (
                        <span
                          key={e}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            fontFamily: 'var(--font-mono)',
                            fontSize: 11,
                            color: 'var(--muted-foreground)',
                          }}
                        >
                          {LinkIcon && <LinkIcon size={10} />}
                          {e}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Portal>
  )
}
