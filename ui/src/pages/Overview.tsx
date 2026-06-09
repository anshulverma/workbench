// Overview page (spec Design Section 2.1).
//
// Six StatCards, four Recharts (wrapped in ChartCard), a recent-jobs DataTable,
// a conditional dead-letter alert banner, and the five UI State Taxonomy states
// (loading / error / empty / unauthorized / degraded).

import { useNavigate } from 'react-router-dom'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { StatCard } from '@/components/StatCard'
import { ChartCard } from '@/components/ChartCard'
import { CHART_COLORS, CHART_PALETTE } from '@/lib/chart-theme'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { HealthBadge } from '@/components/HealthBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import {
  useHealth,
  useIngestionTimeseries,
  useJobs,
  useMessenger,
  useStatsOverview,
  type Job,
} from '@/hooks/useStats'

const PRIORITY_ORDER = ['P0', 'P1', 'P2', 'P3']
const CATEGORY_ORDER = ['action_item', 'meeting', 'plan_seed', 'informational']

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}

function requestIdOf(err: unknown): string | null {
  return err instanceof ApiError ? err.requestId : null
}

const jobColumns: Column<Job>[] = [
  { key: 'id', header: 'ID', render: (j) => <span className="font-mono text-xs">{j.id}</span> },
  { key: 'trigger', header: 'Trigger', render: (j) => j.trigger },
  { key: 'status', header: 'Status', render: (j) => j.status },
  { key: 'items_extracted', header: 'Items', render: (j) => j.items_extracted },
  { key: 'created_at', header: 'Created', render: (j) => relativeTime(j.created_at) },
]

export function Overview() {
  const navigate = useNavigate()
  const overview = useStatsOverview()
  const timeseries = useIngestionTimeseries(14, 'day')
  const jobs = useJobs(10)
  const health = useHealth()
  const messenger = useMessenger()

  // unauthorized: any query failing with a 401 (typically the token endpoint).
  const unauthorizedErr = [overview, timeseries, jobs, health, messenger]
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

  // loading: the primary overview query is still pending.
  if (overview.isPending) {
    return (
      <div data-testid="overview-loading" className="space-y-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
        <Skeleton className="h-48" />
      </div>
    )
  }

  // error: the overview query failed (network / 5xx).
  if (overview.isError) {
    const reqId = requestIdOf(overview.error)
    return (
      <div className="p-6 text-destructive">
        <p>Failed to load overview: {(overview.error as Error).message}</p>
        {reqId && <p className="text-xs">Request ID: {reqId}</p>}
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

  // empty: no activity at all.
  if (allZero) {
    return (
      <EmptyState
        message="No activity yet — add a source to begin"
        cta={
          <button
            className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            onClick={() => navigate('/sources')}
          >
            Add a source
          </button>
        }
      />
    )
  }

  // degraded: messenger not configured (informational, not an error).
  const messengerConfigured = messenger.data?.configured ?? false
  const messengerStatus = messengerConfigured ? 'configured' : 'not-configured'

  // aggregate source health rollup for the Sources stat card.
  const storageHealthy = health.data?.components.storage.status === 'healthy'
  const sourcesHealth = storageHealthy ? 'healthy' : 'erroring'

  const priorityData = PRIORITY_ORDER.map((p) => ({
    name: p,
    value: data.items.by_priority[p] ?? 0,
  }))
  const categoryData = CATEGORY_ORDER.map((c) => ({
    name: c,
    value: data.items.by_category[c] ?? 0,
  }))
  const sourceData = Object.entries(data.items.by_source).map(([name, value]) => ({
    name,
    value,
  }))
  const series = timeseries.data ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Overview</h1>

      {data.dead_letters > 0 && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive"
        >
          <span>
            {data.dead_letters} dead-letter{data.dead_letters === 1 ? '' : 's'} need attention.
          </span>
          <button
            className="text-sm underline"
            onClick={() => navigate('/ingestion')}
          >
            View dead letters
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Pending Triage" value={data.pending_triage} />
        <StatCard label="Ingestion Queue" value={data.in_flight} />
        <StatCard label="Dead Letters" value={data.dead_letters} danger={data.dead_letters > 0} />
        <StatCard label="Active Items" value={data.active_items} />
        <StatCard
          label="Sources"
          value={
            <div className="flex items-center gap-2">
              <span>
                {data.sources_enabled} / {data.sources_total}
              </span>
              {data.sources_total > 0 && <HealthBadge status={sourcesHealth} />}
            </div>
          }
        />
        <StatCard
          label="Messenger"
          value={<HealthBadge status={messengerStatus} />}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title="Ingestion (14 days)" empty={series.length === 0}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={(d) => relativeTime(d)} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="count"
                stroke={CHART_COLORS.primary}
                fill={CHART_COLORS.primary}
                fillOpacity={0.2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Items by Priority"
          empty={priorityData.every((d) => d.value === 0)}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={priorityData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="value" fill={CHART_COLORS.primary} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Items by Source" empty={sourceData.length === 0}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={sourceData}
                dataKey="value"
                nameKey="name"
                innerRadius="55%"
                outerRadius="80%"
              >
                {sourceData.map((_, i) => (
                  <Cell key={i} fill={CHART_PALETTE[i % CHART_PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Items by Category"
          empty={categoryData.every((d) => d.value === 0)}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={categoryData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} />
              <YAxis type="category" dataKey="name" width={110} />
              <Tooltip />
              <Bar dataKey="value" fill={CHART_COLORS.tertiary} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-medium">Recent Jobs</h2>
        {jobs.isPending ? (
          <Skeleton className="h-48" />
        ) : jobs.isError ? (
          <p className="text-sm text-destructive">
            Failed to load jobs: {(jobs.error as Error).message}
          </p>
        ) : (jobs.data?.jobs.length ?? 0) === 0 ? (
          <EmptyState message="No jobs run yet" />
        ) : (
          <DataTable
            columns={jobColumns}
            rows={jobs.data!.jobs}
            rowKey={(j) => j.id}
          />
        )}
      </div>
    </div>
  )
}
