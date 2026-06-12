// Ingestion activity page (spec Design Section 2.4, V3 restructure).
//
// V3 layout: top stat cards (queue stats promoted), LiveTail replacing LogStream,
// Warnings section (dead letters promoted), job history, queue chart, and a
// placeholder for the embedded IngestionFunnel (Slice 12).

import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { StatCard } from '@/components/StatCard'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { ChartCard } from '@/components/ChartCard'
import { LiveTail, type TailEntry } from '@/components/LiveTail'
import { ItemFunnelDialog } from '@/components/funnel/ItemFunnelDialog'
import { Mono } from '@/components/Mono'
import { SectionHeader } from '@/components/SectionHeader'
import {
  CHART_COLORS,
  CHART_DEFAULTS,
  TOOLTIP_CONTENT_STYLE,
} from '@/lib/chart-theme'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import {
  useActivity,
  useDeadLetters,
  useJobs,
  usePurgeDeadLetter,
  useQueueStats,
  useRetryDeadLetter,
  useSourcesRollup,
  type ActivityItem,
  type DeadLetterEntry,
  type Job,
} from '@/hooks/useStats'

// Slice 12: Real IngestionFunnel component, embedded.
import { IngestionFunnel } from '@/pages/Filters'

const JOB_STATUSES = ['queued', 'pending', 'running', 'completed', 'failed']
const PAGE_SIZE = 25
const TAIL_CAP = 60

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

function requestIdOf(err: unknown): string | null {
  return err instanceof ApiError ? err.requestId : null
}

/** Map an ActivityItem into a TailEntry for the LiveTail component. */
function activityToTailEntry(item: ActivityItem, index: number): TailEntry {
  return {
    key: `${item.id}-${index}`,
    timestamp: item.created_at ? new Date(item.created_at).getTime() : Date.now(),
    itemId: item.id,
    source: item.source_type ?? '?',
    funnelStage: item.status ?? 'unknown',
    outcome: statusToOutcome(item.status),
    summary: item.summary ?? undefined,
  }
}

function statusToOutcome(status: string | null): TailEntry['outcome'] {
  switch (status) {
    case 'active':
    case 'completed':
      return 'include'
    case 'failed':
    case 'error':
      return 'drop'
    case 'filtered':
      return 'drop'
    case 'pending':
    case 'queued':
      return 'pass'
    default:
      return 'pass'
  }
}

function DeadLetterTable() {
  const deadLetters = useDeadLetters()
  const retry = useRetryDeadLetter()
  const purge = usePurgeDeadLetter()
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const columns: Column<DeadLetterEntry>[] = [
    {
      key: 'source_type',
      header: 'Source',
      render: (d) => <span className="font-mono text-xs">{d.source_type}</span>,
    },
    {
      key: 'attempt',
      header: 'Attempts',
      render: (d) => `${d.attempt}/${d.max_attempts}`,
    },
    {
      key: 'error',
      header: 'Error',
      render: (d) => (
        <span className="text-destructive">{d.error ?? '—'}</span>
      ),
    },
    {
      key: 'created_at',
      header: 'When',
      render: (d) => relativeTime(d.created_at),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (d) => (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={retry.isPending}
            onClick={() => retry.mutate(d.id)}
          >
            Retry
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={purge.isPending}
            onClick={() => setConfirmId(d.id)}
          >
            Purge
          </Button>
        </div>
      ),
    },
  ]

  if (deadLetters.isPending) return <Skeleton className="h-32" />
  if (deadLetters.isError) {
    const reqId = requestIdOf(deadLetters.error)
    return (
      <p className="text-sm text-destructive">
        Failed to load dead letters: {(deadLetters.error as Error).message}
        {reqId && ` (req ${reqId})`}
      </p>
    )
  }
  const rows = deadLetters.data ?? []
  if (rows.length === 0) {
    return <EmptyState message="No dead letters — queue is clean" />
  }
  return (
    <>
      <DataTable columns={columns} rows={rows} rowKey={(d) => d.id} />
      <Dialog open={confirmId !== null} onOpenChange={(o) => !o && setConfirmId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Purge dead letter?</DialogTitle>
            <DialogDescription>
              This permanently deletes the entry. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (confirmId) purge.mutate(confirmId)
                setConfirmId(null)
              }}
            >
              Purge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

const jobColumns: Column<Job>[] = [
  {
    key: 'id',
    header: 'ID',
    render: (j) => <span className="font-mono text-xs">{j.id}</span>,
  },
  { key: 'trigger', header: 'Trigger', render: (j) => j.trigger },
  { key: 'status', header: 'Status', render: (j) => j.status },
  { key: 'items_extracted', header: 'Items', render: (j) => j.items_extracted },
  {
    key: 'created_at',
    header: 'Created',
    render: (j) => relativeTime(j.created_at),
  },
]

export function Ingestion() {
  const [statusFilter, setStatusFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [tailLive, setTailLive] = useState(true)
  const [tailItemId, setTailItemId] = useState<string | null>(null)

  const sources = useSourcesRollup()
  const activity = useActivity(50)
  const jobs = useJobs(PAGE_SIZE, offset, statusFilter || undefined)
  const queue = useQueueStats()
  const deadLetters = useDeadLetters()

  // Map activity items into TailEntry objects for LiveTail, capped at TAIL_CAP.
  const tailEntries = useMemo<TailEntry[]>(
    () => (activity.data ?? []).slice(0, TAIL_CAP).map(activityToTailEntry),
    [activity.data],
  )

  // Build a minimal FunnelItem-compatible object for ItemFunnelDialog from the
  // clicked activity item. The dialog degrades gracefully with minimal data.
  const tailItem = useMemo(() => {
    if (!tailItemId) return null
    const act = (activity.data ?? []).find((a) => a.id === tailItemId)
    if (!act) return null
    return {
      id: act.id,
      summary: act.summary ?? '(no summary)',
      source: act.source_type ?? 'unknown',
      created_at: act.created_at ?? new Date().toISOString(),
      stages: [],
      verdict: {
        decision: 'queued' as const,
        rationale: `Activity status: ${act.status}`,
      },
    }
  }, [tailItemId, activity.data])

  // unauthorized: any query failing with a 401.
  const unauthorizedErr = [sources, activity, jobs, queue]
    .map((q) => q.error)
    .find(isUnauthorized)
  if (unauthorizedErr) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-10 text-center text-muted-foreground">
        <p className="text-lg font-medium">token unavailable</p>
        <p className="text-sm">
          Check that the SSH tunnel is up and the server is bound to loopback.
        </p>
      </div>
    )
  }

  // loading: the primary sources query is still pending.
  if (sources.isPending) {
    return (
      <div data-testid="ingestion-loading" className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-48" />
      </div>
    )
  }

  // error: the sources query failed (network / 5xx).
  if (sources.isError) {
    const reqId = requestIdOf(sources.error)
    return (
      <div className="p-6 text-destructive">
        <p>Failed to load sources: {(sources.error as Error).message}</p>
        {reqId && <p className="text-xs">Request ID: {reqId}</p>}
      </div>
    )
  }

  const queueData = queue.data
  const queueChart = queueData
    ? Object.entries(queueData.by_status).map(([name, value]) => ({ name, value }))
    : []
  const queueDegraded = queue.isError
  const deadCount = deadLetters.data?.length ?? 0

  const total = jobs.data?.total ?? 0
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-2xl font-semibold">Ingestion</h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Live pipeline state, warnings, and the ingestion funnel every item flows through.
        </p>
      </div>

      {/* 1 — Top-level queue stat cards (promoted from Queue Health section) */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="In Queue"
          value={
            queueDegraded ? '—' : (
              <span className="flex items-baseline gap-2">
                <Mono className="text-2xl font-bold">{queueData?.queued ?? 0}</Mono>
                <span className="text-xs text-muted-foreground">
                  +{queueData?.processing ?? 0} processing
                </span>
              </span>
            )
          }
        />
        <StatCard label="Processing" value={queueDegraded ? '—' : (queueData?.processing ?? 0)} />
        <StatCard
          label="Dead Letters"
          value={queueDegraded ? '—' : (queueData?.dead_letter ?? 0)}
          danger={(queueData?.dead_letter ?? 0) > 0}
        />
        <StatCard
          label="Sources"
          value={sources.data?.length ?? 0}
          delta={`${sources.data?.filter((s) => s.enabled).length ?? 0} enabled`}
        />
      </div>

      {/* 2 — LiveTail + Queue chart side by side */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="space-y-2.5" aria-label="live funnel tail">
          <SectionHeader
            right={
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded border border-border bg-transparent px-2 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-accent"
                onClick={() => setTailLive((v) => !v)}
                aria-pressed={tailLive}
                style={tailLive ? { borderColor: 'color-mix(in srgb, var(--success, #22c55e) 40%, transparent)', background: 'color-mix(in srgb, var(--success, #22c55e) 12%, transparent)', color: 'var(--success, #22c55e)' } : undefined}
              >
                <span
                  className="inline-block h-[7px] w-[7px] rounded-full"
                  style={{
                    background: tailLive ? 'var(--success, #22c55e)' : 'var(--muted-foreground)',
                    animation: tailLive ? 'wb-pulse 1.6s ease infinite' : 'none',
                  }}
                />
                {tailLive ? 'live' : 'paused'}
              </button>
            }
          >
            Live Funnel Tail
          </SectionHeader>
          <LiveTail
            entries={tailEntries}
            live={tailLive}
            onToggleLive={() => setTailLive((v) => !v)}
            onOpenItem={setTailItemId}
            error={activity.isError ? `Failed to load activity: ${(activity.error as Error).message}` : undefined}
          />
        </section>

        <section className="space-y-2.5" aria-label="queue by status">
          <SectionHeader>Queue by Status</SectionHeader>
          {queueDegraded ? (
            <p className="text-sm text-amber-600">
              Queue stats unavailable — showing partial data.
            </p>
          ) : (
            <ChartCard title="Queue by status" empty={queueChart.length === 0}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={queueChart}>
                  <CartesianGrid
                    stroke={CHART_DEFAULTS.grid.stroke}
                    strokeDasharray={CHART_DEFAULTS.grid.strokeDasharray}
                  />
                  <XAxis
                    dataKey="name"
                    stroke={CHART_DEFAULTS.axis.stroke}
                    fontSize={CHART_DEFAULTS.axis.fontSize}
                  />
                  <YAxis
                    allowDecimals={false}
                    stroke={CHART_DEFAULTS.axis.stroke}
                    fontSize={CHART_DEFAULTS.axis.fontSize}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_CONTENT_STYLE}
                    cursor={{ fill: 'transparent' }}
                  />
                  <Bar dataKey="value" fill={CHART_COLORS.primary} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          )}
        </section>
      </div>

      {/* 3 — Warnings: dead letters promoted to prominent position */}
      <section className="space-y-2.5" aria-label="warnings">
        <SectionHeader
          right={
            deadCount > 0 ? (
              <span className="font-mono text-[11px] text-error-text">
                {deadCount} need attention
              </span>
            ) : null
          }
        >
          Warnings
        </SectionHeader>
        {deadCount > 0 && (
          <div
            role="alert"
            className="flex items-center gap-2.5 rounded border border-destructive/50 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-error-text"
          >
            <Mono className="font-bold">{deadCount}</Mono> dead letter{deadCount === 1 ? '' : 's'} — items that exhausted their retries. Retry or purge below.
          </div>
        )}
        <DeadLetterTable />
      </section>

      {/* 4 — Job history */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <SectionHeader>Job History</SectionHeader>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Status</span>
            <select
              aria-label="Job status filter"
              className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                setOffset(0)
              }}
            >
              <option value="">all</option>
              {JOB_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
        {jobs.isPending ? (
          <Skeleton className="h-48" />
        ) : jobs.isError ? (
          <p className="text-sm text-destructive">
            Failed to load jobs: {(jobs.error as Error).message}
          </p>
        ) : (jobs.data?.jobs.length ?? 0) === 0 ? (
          <EmptyState message="No jobs match this filter" />
        ) : (
          <>
            <DataTable columns={jobColumns} rows={jobs.data!.jobs} rowKey={(j) => j.id} />
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!canPrev}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!canNext}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </section>

      {/* 5 — Embedded Ingestion Funnel (Slice 12) */}
      <section className="space-y-2.5" aria-label="ingestion funnel">
        <SectionHeader
          right={
            <span className="font-mono text-[11px] text-muted-foreground">
              enrichers + filters, in order
            </span>
          }
        >
          Ingestion Funnel
        </SectionHeader>
        <IngestionFunnel embedded />
      </section>

      {/* ItemFunnelDialog — opened by clicking a LiveTail row */}
      <ItemFunnelDialog
        item={tailItem}
        open={!!tailItem}
        onClose={() => setTailItemId(null)}
      />
    </div>
  )
}
