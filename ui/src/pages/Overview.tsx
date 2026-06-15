// Overview page — mission-control landing.
//
// Mirrors the design prototype (page-overview.jsx): a compact clickable status
// strip, the Signal Flow Sankey hero, and a full-width Hot Feed. The legacy
// topology / charts / recent-jobs sections were removed (reserved for a future
// stats page). Five UI states preserved (loading / error / empty / unauthorized
// / degraded).

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, ChevronRight, CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SourceFlow } from '@/components/SourceFlow'
import { ItemFunnelDialog } from '@/components/funnel/ItemFunnelDialog'
import { buildFlowMatrix } from '@/lib/funnel-helpers'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import {
  useHealth,
  useMessenger,
  useSourcesRollup,
  useStatsOverview,
} from '@/hooks/useStats'
import { useHotFeed, type Item } from '@/hooks/useItems'

const PRIORITY_VARIANT: Record<string, 'p0' | 'p1' | 'p2' | 'p3'> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
}

/** Render a 0..1 ratio metric as a whole-number percent, or "n/a" when null. */
function pct(value: number | null | undefined): string {
  return value == null ? 'n/a' : `${Math.round(value * 100)}%`
}

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

// --- Hot Feed: full-width card; rows open the item funnel dialog. ---

function HotFeed({ onOpen }: { onOpen: (item: Item) => void }) {
  const feed = useHotFeed()
  return (
    <Card data-testid="hot-feed" className="flex flex-col">
      <CardHeader className="border-b border-border" style={{ padding: '16px 20px' }}>
        <CardTitle className="wb-section-h">Hot Feed</CardTitle>
      </CardHeader>
      <CardContent className="flex-1" style={{ padding: 16 }}>
        {feed.isPending ? (
          <Skeleton className="h-24" />
        ) : feed.isError ? (
          <p className="text-sm text-destructive">Feed unavailable</p>
        ) : feed.items.length === 0 ? (
          <p className="font-mono text-xs text-muted-foreground">
            // No high-priority signals pending
          </p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 10 }}>
            {feed.items.map((it: Item) => (
              <li key={it.id} style={{ borderBottom: '1px solid var(--border)' }}>
                <button
                  data-testid={`hot-feed-item-${it.id}`}
                  onClick={() => onOpen(it)}
                  className="hover:bg-accent"
                  style={{
                    display: 'flex', gap: 10, alignItems: 'flex-start', width: '100%',
                    textAlign: 'left', padding: '0 0 10px', background: 'none', border: 0,
                    cursor: 'pointer', borderRadius: 'var(--radius-control, 4px)',
                  }}
                >
                  <Badge variant={PRIORITY_VARIANT[it.priority] ?? 'p3'}>{it.priority}</Badge>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.4, color: 'var(--foreground)' }}>
                      {it.summary}
                    </p>
                    <p style={{ margin: '3px 0 0', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted-foreground)' }}>
                      <span style={{ color: 'var(--tertiary)' }}>{it.id}</span> · {it.source_type} · {relativeTime(it.created_at)}
                    </p>
                  </div>
                  <ChevronRight size={15} style={{ color: 'var(--muted-foreground)', flexShrink: 0, alignSelf: 'center' }} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

interface StripTile {
  label: string
  value: React.ReactNode
  to: string
  danger?: boolean
}

export function Overview() {
  const navigate = useNavigate()
  const overview = useStatsOverview()
  const health = useHealth()
  const messenger = useMessenger()
  const sourcesRollup = useSourcesRollup()
  const [openItem, setOpenItem] = useState<Item | null>(null)

  const unauthorizedErr = [overview, health, messenger].map((q) => q.error).find(isUnauthorized)
  if (unauthorizedErr) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-10 text-center text-muted-foreground">
        <p className="text-lg font-medium">token unavailable</p>
        <p className="text-sm">Check that the SSH tunnel is up and the server is bound to loopback.</p>
      </div>
    )
  }

  if (overview.isPending) {
    return (
      <div data-testid="overview-loading" className="grid gap-6">
        <Skeleton className="h-8 w-40" />
        <div className="grid grid-cols-7 gap-2.5">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-72" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (overview.isError) {
    return (
      <div className="p-6 text-destructive">
        <p>Failed to load overview: {(overview.error as Error).message}</p>
      </div>
    )
  }

  const data = overview.data
  const allZero =
    data.items.total === 0 &&
    data.pending_triage === 0 &&
    data.in_flight === 0 &&
    data.dead_letters === 0 &&
    data.sources_total === 0

  if (allZero) {
    return (
      <div style={{ display: 'grid', gap: 24 }} className="wb-enter">
        <h1 className="wb-h1">Overview</h1>
        <EmptyState
          message="// No activity yet — add a source to begin"
          cta={
            <button
              className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
              onClick={() => navigate('/sources')}
            >
              Add a source
            </button>
          }
        />
      </div>
    )
  }

  const metrics = data.metrics
  const messengerConfigured = messenger.data?.configured ?? false
  const deadLetters = data.dead_letters

  const tiles: (StripTile | null)[] = [
    { label: 'Ingestion Queue', value: data.in_flight, to: '/ingestion' },
    { label: 'Ingest Rate', value: pct(metrics?.ingestion_success_rate), to: '/ingestion' },
    deadLetters > 0
      ? { label: 'Dead Letters', value: deadLetters, to: '/ingestion', danger: true }
      : null,
    { label: 'Active Items', value: data.active_items, to: '/actions' },
    {
      label: 'Sources',
      value: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Mono style={{ fontSize: 20, fontWeight: 700, color: 'var(--foreground)' }}>
            {data.sources_enabled}/{data.sources_total}
          </Mono>
          <span
            title="healthy"
            aria-label="healthy"
            style={{ width: 9, height: 9, borderRadius: 9999, background: 'var(--success, #9ad08a)', flexShrink: 0 }}
          />
        </span>
      ),
      to: '/settings/sources',
    },
    {
      label: 'Messenger',
      value: messengerConfigured ? (
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <CircleCheck size={15} style={{ color: 'var(--success, #9ad08a)' }} />
          <span style={{ fontSize: 17, fontWeight: 700, color: 'var(--foreground)' }}>GChat</span>
        </span>
      ) : (
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <CircleAlert size={15} style={{ color: 'var(--brand)' }} />
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--brand)' }}>Unset</span>
        </span>
      ),
      to: '/settings/messenger',
    },
  ]
  const cols = deadLetters > 0 ? 8 : 7

  return (
    <div style={{ display: 'grid', gap: 24 }} className="wb-enter">
      <h1 className="wb-h1">Overview</h1>

      {/* Status strip — compact, every tile navigates to its page */}
      <div data-testid="status-strip" style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 10 }}>
        <button
          className="wb-tile-primary"
          onClick={() => navigate('/triage')}
          style={{ gridColumn: 'span 2', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', opacity: 0.85 }}>
            Initiate Triage <ArrowRight size={13} />
          </span>
          <span style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <Mono style={{ fontSize: 24, fontWeight: 700 }}>{data.pending_triage}</Mono>
            <span style={{ fontSize: 13, fontWeight: 500 }}>
              pending · {data.items.by_priority.P0 ?? 0} P0 active
            </span>
          </span>
        </button>
        {tiles.filter((t): t is StripTile => t !== null).map((c) => (
          <button
            key={c.label}
            className={`wb-tile ${c.danger ? 'wb-tile--danger' : ''}`}
            onClick={() => navigate(c.to)}
            style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}
          >
            <span className="wb-section-h" style={{ fontSize: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              {c.label}
              <ArrowUpRight size={12} className="wb-tile-arrow" />
            </span>
            {typeof c.value === 'object' ? (
              c.value
            ) : (
              <Mono style={{ fontSize: 20, fontWeight: 700, color: c.danger ? 'var(--destructive)' : 'var(--foreground)' }}>
                {c.value}
              </Mono>
            )}
          </button>
        ))}
      </div>

      {/* Signal Flow — animated Sankey: sources → WorkBench → outputs */}
      <Card data-testid="signal-flow-card">
        <CardHeader className="flex flex-row items-baseline justify-between border-b border-border" style={{ padding: '16px 20px' }}>
          <CardTitle className="wb-section-h">Signal Flow</CardTitle>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted-foreground)' }}>
            sources → workbench → outputs · hover to isolate
          </span>
        </CardHeader>
        <CardContent style={{ padding: '12px 16px 28px' }}>
          <SourceFlow
            data={
              sourcesRollup.data
                ? buildFlowMatrix(
                    Object.fromEntries(sourcesRollup.data.map((s) => [s.adapter_type, s.items_stored])),
                    {
                      action_items: data.active_items,
                      triage_queue: data.pending_triage,
                      filtered_out: data.in_flight,
                      errors: data.dead_letters,
                    },
                  )
                : undefined
            }
            stalledSources={
              sourcesRollup.data
                ? new Set(
                    sourcesRollup.data
                      .filter((s) => s.health_status === 'erroring')
                      .map((s) => s.adapter_type),
                  )
                : undefined
            }
            ingestRate={metrics?.throughput ?? 0}
            egressRate={metrics?.signal_velocity ?? 0}
            error={sourcesRollup.isError ? (sourcesRollup.error as Error).message : undefined}
            onNavigate={navigate}
          />
        </CardContent>
      </Card>

      {!messengerConfigured && (
        <div
          role="status"
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
            border: '1px solid color-mix(in srgb, var(--primary) 45%, transparent)',
            borderRadius: 'var(--radius-control, 4px)',
            background: 'color-mix(in srgb, var(--primary) 8%, transparent)',
          }}
        >
          <TriangleAlert size={15} style={{ color: 'var(--brand)' }} />
          <span style={{ fontSize: 13 }}>
            Messenger not configured — triage cards are queued but unsent. Partial functionality.
          </span>
        </div>
      )}

      {/* Hero: hot feed full-width */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 16 }}>
        <HotFeed onOpen={setOpenItem} />
      </div>

      <ItemFunnelDialog
        item={
          openItem
            ? {
                id: openItem.id,
                summary: openItem.summary,
                source: openItem.source_type,
                created_at: openItem.created_at,
                stages: [],
                verdict: {
                  decision: 'queued',
                  priority: openItem.priority,
                  rationale: 'Pending triage — awaiting funnel treatment.',
                },
              }
            : null
        }
        open={!!openItem}
        onClose={() => setOpenItem(null)}
      />
    </div>
  )
}
