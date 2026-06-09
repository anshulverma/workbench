// Ingestion activity page (spec Design Section 2.4).
//
// Per-source panels (adapter type, enabled badge, schedule, last-run, qualified
// Ingested Counts, Source Health Status, recent-items expander), an activity
// feed, a job-history DataTable with status filter + offset pagination, and a
// queue-health panel with a dead-letter DataTable (per-row Retry + Purge, where
// Purge is behind a confirm dialog). Implements the five UI States (loading /
// error w/ X-Request-ID / empty / unauthorized / degraded).

import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
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
import { HealthBadge } from '@/components/HealthBadge'
import { ChartCard } from '@/components/ChartCard'
import { CHART_COLORS } from '@/lib/chart-theme'
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
  type SourceRollup,
} from '@/hooks/useStats'

const JOB_STATUSES = ['queued', 'pending', 'running', 'completed', 'failed']
const PAGE_SIZE = 25

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

function requestIdOf(err: unknown): string | null {
  return err instanceof ApiError ? err.requestId : null
}

function SourcePanel({ source }: { source: SourceRollup }) {
  const [open, setOpen] = useState(false)
  const recent = useActivity(50)
  const recentForSource = (recent.data ?? []).filter(
    (i) => i.source_type === source.adapter_type,
  )
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">
            {source.adapter_type}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={source.enabled ? 'default' : 'secondary'}>
              {source.enabled ? 'enabled' : 'disabled'}
            </Badge>
            <HealthBadge status={source.health_status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-1 text-muted-foreground">
          <span>Schedule</span>
          <span className="text-right font-mono text-foreground">
            {source.schedule ?? '—'}
          </span>
          <span>Last run</span>
          <span className="text-right text-foreground">
            {relativeTime(source.last_run)}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <div className="text-lg font-bold">{source.items_stored}</div>
            <div className="text-xs text-muted-foreground">stored</div>
          </div>
          <div>
            <div className="text-lg font-bold">{source.raw_enqueued}</div>
            <div className="text-xs text-muted-foreground">raw enqueued</div>
          </div>
          <div>
            <div className="text-lg font-bold">{source.in_flight}</div>
            <div className="text-xs text-muted-foreground">in flight</div>
          </div>
        </div>
        <button
          type="button"
          className="text-xs text-primary underline"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Hide recent items' : 'Show recent items'}
        </button>
        {open && (
          <ul className="space-y-1 border-t pt-2 text-xs">
            {recentForSource.length === 0 ? (
              <li className="text-muted-foreground">No recent items.</li>
            ) : (
              recentForSource.slice(0, 5).map((i) => (
                <li key={i.id} className="truncate">
                  {i.summary ?? '(no summary)'}
                </li>
              ))
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

const activityColumns: Column<ActivityItem>[] = [
  {
    key: 'source_type',
    header: 'Source',
    render: (i) => <span className="font-mono text-xs">{i.source_type}</span>,
  },
  { key: 'status', header: 'Status', render: (i) => i.status },
  { key: 'summary', header: 'Summary', render: (i) => i.summary ?? '—' },
  {
    key: 'created_at',
    header: 'When',
    render: (i) => relativeTime(i.created_at),
  },
]

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

export function Ingestion() {
  const [statusFilter, setStatusFilter] = useState('')
  const [offset, setOffset] = useState(0)

  const sources = useSourcesRollup()
  const activity = useActivity(50)
  const jobs = useJobs(PAGE_SIZE, offset, statusFilter || undefined)
  const queue = useQueueStats()

  // unauthorized: any query failing with a 401 (typically the token endpoint).
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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48" />
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

  const sourceList = sources.data
  const queueData = queue.data
  const queueChart = queueData
    ? Object.entries(queueData.by_status).map(([name, value]) => ({ name, value }))
    : []
  // degraded: queue stats failed to load but the page still renders.
  const queueDegraded = queue.isError

  const total = jobs.data?.total ?? 0
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Ingestion</h1>

      {/* Per-source panels */}
      <section className="space-y-2" aria-label="sources">
        <h2 className="text-lg font-medium">Sources</h2>
        {sourceList.length === 0 ? (
          <EmptyState message="No sources configured yet" />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {sourceList.map((s) => (
              <SourcePanel key={s.id} source={s} />
            ))}
          </div>
        )}
      </section>

      {/* Activity feed */}
      <section className="space-y-2">
        <h2 className="text-lg font-medium">Recent Activity</h2>
        {activity.isPending ? (
          <Skeleton className="h-48" />
        ) : activity.isError ? (
          <p className="text-sm text-destructive">
            Failed to load activity: {(activity.error as Error).message}
          </p>
        ) : (activity.data?.length ?? 0) === 0 ? (
          <EmptyState message="No recent activity" />
        ) : (
          <DataTable
            columns={activityColumns}
            rows={activity.data!}
            rowKey={(i) => i.id}
          />
        )}
      </section>

      {/* Job history */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Job History</h2>
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

      {/* Queue health + dead letters */}
      <section className="space-y-2">
        <h2 className="text-lg font-medium">Queue Health</h2>
        {queueDegraded ? (
          <p className="text-sm text-amber-600">
            Queue stats unavailable — showing partial data.
          </p>
        ) : queueData ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="Queued" value={queueData.queued} />
              <StatCard label="Processing" value={queueData.processing} />
              <StatCard
                label="Dead Letters"
                value={queueData.dead_letter}
                danger={queueData.dead_letter > 0}
              />
            </div>
            <ChartCard title="Queue by status" empty={queueChart.length === 0}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={queueChart}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="value" fill={CHART_COLORS.primary} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        ) : (
          <Skeleton className="h-24" />
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Dead Letters</h2>
        <DeadLetterTable />
      </section>
    </div>
  )
}
