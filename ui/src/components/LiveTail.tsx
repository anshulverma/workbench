import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import * as Icons from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Mono } from '@/components/Mono'
import { ActionChip } from '@/components/ActionChip'
import { SRC_ICON } from '@/lib/funnel-constants'
import type { StageOutcome } from '@/lib/types/funnel'
import { cn } from '@/lib/utils'

function getIcon(name: string): LucideIcon | undefined {
  return (Icons as unknown as Record<string, LucideIcon>)[name]
}

/** A single event passing through the ingestion funnel. */
export interface TailEntry {
  /** Unique row key (e.g. `${itemId}-${stageIndex}`). */
  key: string
  /** Epoch ms timestamp for the event. */
  timestamp: number
  /** Short item id (e.g. "it_abc12"). */
  itemId: string
  /** Source adapter name (e.g. "github"). */
  source: string
  /** Human-readable funnel stage label (e.g. "f_priority · auto-include"). */
  funnelStage: string
  /** Stage outcome for ActionChip rendering. */
  outcome: StageOutcome
  /** Optional confidence score. */
  confidence?: number
  /** Optional label (for "label" outcome). */
  label?: string
  /** Item summary for screen readers / tooltips. */
  summary?: string
  /** Lineage path id (e.g. "5.1"). Presence-gated link (Task 14): rendered only
   *  when present, a no-op today since the activity payload omits it. */
  path?: string
}

const TAIL_CAP = 60
const COLUMNS = ['Time', 'Item', 'Source', 'Funnel stage', 'Status'] as const

/**
 * LiveTail — auto-scrolling structured table that streams ingestion funnel events.
 *
 * Five columns (Time, Item ID, Source, Funnel stage, Status), fixed height 226px,
 * capped at 60 rows. The newest row receives the `wb-tail-new` flash animation.
 * A live/paused toggle button controls whether new rows append. Clicking a row
 * fires `onOpenItem` with the item ID so the parent can open ItemFunnelDialog.
 *
 * Five UI states: loading (no entries yet + not paused), empty (no entries +
 * paused), streaming (normal), paused (frozen tail), error (fallback).
 */
export function LiveTail({
  entries,
  live = true,
  onToggleLive,
  onOpenItem,
  error,
  className,
}: {
  /** The tail entries to display. Parent is responsible for polling and
   *  appending; LiveTail only renders + caps at 60. */
  entries: TailEntry[]
  /** Whether the tail is streaming (true) or paused (false). */
  live?: boolean
  /** Called when the user clicks the live/paused toggle. */
  onToggleLive?: () => void
  /** Called when a row is clicked, with the item ID. */
  onOpenItem?: (itemId: string) => void
  /** If set, renders an error state instead of the table. */
  error?: string
  className?: string
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [prevCount, setPrevCount] = useState(entries.length)

  // Auto-scroll to bottom when new entries arrive (only when live).
  useEffect(() => {
    if (!live) return
    if (entries.length !== prevCount) {
      const el = scrollRef.current
      if (el) {
        if (typeof el.scrollTo === 'function') {
          const reduced =
            typeof window !== 'undefined' &&
            window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
          el.scrollTo({ top: el.scrollHeight, behavior: reduced ? 'auto' : 'smooth' })
        } else {
          el.scrollTop = el.scrollHeight
        }
      }
      setPrevCount(entries.length)
    }
  }, [entries.length, live, prevCount])

  const handleRowClick = useCallback(
    (itemId: string) => {
      onOpenItem?.(itemId)
    },
    [onOpenItem],
  )

  const formatTime = (ts: number) =>
    new Date(ts).toLocaleTimeString([], { hour12: false })

  const capped = entries.slice(-TAIL_CAP)

  const PauseIcon = getIcon('Pause')
  const PlayIcon = getIcon('Play')

  // Error state
  if (error) {
    return (
      <div
        className={cn(
          'rounded-md border border-border bg-card p-6 text-center text-sm text-destructive',
          className,
        )}
        role="alert"
      >
        {error}
      </div>
    )
  }

  return (
    <div
      className={cn('overflow-hidden rounded-md border border-border bg-card', className)}
      data-testid="live-tail"
    >
      {/* Column headers */}
      <div
        className="grid items-center gap-2 border-b border-border bg-surface-high px-3.5 py-2"
        style={{ gridTemplateColumns: '62px 80px 78px minmax(0,1fr) 118px' }}
        role="row"
      >
        {COLUMNS.map((h, i) => (
          <span
            key={h}
            className="font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
            style={{ textAlign: i === 4 ? 'right' : 'left' }}
            role="columnheader"
          >
            {h}
          </span>
        ))}
      </div>

      {/* Scrollable row area */}
      <div
        ref={scrollRef}
        className="overflow-y-auto"
        style={{ height: 226 }}
        role="log"
        aria-live={live ? 'polite' : 'off'}
        aria-label="Live funnel tail"
      >
        {capped.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {live ? 'Waiting for events...' : '// tail paused — no entries'}
          </div>
        ) : (
          capped.map((entry, idx) => {
            const isNewest = idx === capped.length - 1
            const srcIconName = SRC_ICON[entry.source] ?? 'Database'
            const SrcIcon = getIcon(srcIconName)

            return (
              <button
                key={entry.key}
                type="button"
                className={cn(
                  'grid w-full items-center gap-2 border-b border-border/55 bg-transparent px-3.5 py-[7px] text-left transition-colors hover:bg-accent',
                  isNewest ? 'wb-tail-new' : '',
                )}
                style={{ gridTemplateColumns: '62px 80px 78px minmax(0,1fr) 118px' }}
                onClick={() => handleRowClick(entry.itemId)}
                title={`Open ${entry.itemId}`}
              >
                <Mono className="text-[11px] text-muted-foreground">
                  {formatTime(entry.timestamp)}
                </Mono>
                <Mono className="truncate text-xs text-tertiary">
                  {entry.path ? (
                    <Link
                      to={`/items/${entry.path}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-primary hover:underline"
                    >
                      #{entry.path}
                    </Link>
                  ) : (
                    entry.itemId
                  )}
                </Mono>
                <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                  {SrcIcon && <SrcIcon size={12} />}
                  {entry.source}
                </span>
                <span className="min-w-0 truncate text-[13px]">
                  {entry.funnelStage}
                  {entry.summary && (
                    <span className="ml-1 text-[11px] text-muted-foreground">
                      {entry.summary}
                    </span>
                  )}
                </span>
                <span className="justify-self-end">
                  <ActionChip
                    action={entry.outcome}
                    label={entry.label}
                    confidence={entry.confidence}
                    small
                  />
                </span>
              </button>
            )
          })
        )}
      </div>

      {/* Footer with live/paused toggle */}
      <div className="flex items-center justify-between border-t border-border px-3.5 py-1.5">
        <span className="font-mono text-[11px] text-muted-foreground">
          {capped.length} / {TAIL_CAP}
        </span>
        <button
          type="button"
          className={cn(
            'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[11px] transition-colors',
            live
              ? 'border-green-500/40 bg-green-500/10 text-green-500'
              : 'border-border bg-transparent text-muted-foreground',
          )}
          onClick={onToggleLive}
          aria-pressed={live}
          data-testid="live-toggle"
        >
          <span
            className={cn(
              'inline-block h-[7px] w-[7px] rounded-full',
              live ? 'bg-green-500 animate-pulse' : 'bg-muted-foreground',
            )}
          />
          {live ? 'live' : 'paused'}
          {live
            ? PauseIcon && <PauseIcon size={11} />
            : PlayIcon && <PlayIcon size={11} />}
        </button>
      </div>
    </div>
  )
}
