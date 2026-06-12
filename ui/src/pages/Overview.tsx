// Overview page (spec Design Section 2.1).
//
// Six StatCards, four Recharts (wrapped in ChartCard), a recent-jobs DataTable,
// a conditional dead-letter alert banner, and the five UI State Taxonomy states
// (loading / error / empty / unauthorized / degraded).

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
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
import { Sparkline } from '@/components/Sparkline'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Topology } from '@/components/Topology'
import { SourceFlow } from '@/components/SourceFlow'
import { ItemFunnelDialog } from '@/components/funnel/ItemFunnelDialog'
import {
  CHART_COLORS,
  CHART_DEFAULTS,
  CHART_PALETTE,
  TOOLTIP_CONTENT_STYLE,
} from '@/lib/chart-theme'
import { buildFlowMatrix } from '@/lib/funnel-helpers'
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
  useMetricsTimeseries,
  useSourcesRollup,
  useStatsOverview,
  type Job,
} from '@/hooks/useStats'
import { useHotFeed, type Item } from '@/hooks/useItems'
import { useTopology } from '@/hooks/useTopology'

const PRIORITY_ORDER = ['P0', 'P1', 'P2', 'P3']
const CATEGORY_ORDER = ['action_item', 'meeting', 'plan_seed', 'informational']

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

// --- Hero widgets (spec §8). Each fails soft inline: it renders its own
// loading / empty / error state and never blocks the page-level gates. ---

function HotFeed({ onOpen }: { onOpen: (item: Item) => void }) {
  const feed = useHotFeed()
  return (
    <Card data-testid="hot-feed" className="flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Hot Feed
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 space-y-2">
        {feed.isPending ? (
          <Skeleton className="h-24" />
        ) : feed.isError ? (
          <p className="text-sm text-destructive">Feed unavailable</p>
        ) : feed.items.length === 0 ? (
          <p className="font-mono text-xs text-muted-foreground">
            // No high-priority signals pending
          </p>
        ) : (
          <ul className="space-y-2">
            {feed.items.map((it: Item) => (
              <li
                key={it.id}
                className="border-b border-border last:border-b-0"
              >
                <button
                  data-testid={`hot-feed-item-${it.id}`}
                  onClick={() => onOpen(it)}
                  className="flex w-full items-start gap-2 rounded pb-2 text-left hover:bg-accent"
                  style={{ background: 'none', border: 0, cursor: 'pointer' }}
                >
                  <Badge variant={PRIORITY_VARIANT[it.priority] ?? 'p3'}>
                    {it.priority}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">{it.summary}</p>
                    <p className="font-mono text-xs text-muted-foreground">
                      {it.source_type} · {relativeTime(it.created_at)}
                    </p>
                  </div>
                  <ChevronRight
                    size={15}
                    className="mt-0.5 flex-shrink-0 text-muted-foreground"
                  />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function TopologyPanel() {
  const topology = useTopology()
  return (
    <Card data-testid="topology-panel">
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Infrastructure
        </CardTitle>
      </CardHeader>
      <CardContent>
        {topology.isPending ? (
          <Skeleton className="h-48" />
        ) : topology.isError ? (
          <p className="text-sm text-destructive">Topology unavailable</p>
        ) : (topology.data?.nodes.length ?? 0) === 0 ? (
          <p className="font-mono text-xs text-muted-foreground">
            // No components discovered
          </p>
        ) : (
          <Topology data={topology.data!} />
        )}
      </CardContent>
    </Card>
  )
}

function SignalVelocityTile() {
  const series = useMetricsTimeseries('signal_velocity', 24, 'hour')
  return (
    <StatCard
      label="Signal Velocity (24h)"
      value={
        series.isError ? 'n/a' : <Mono>{series.data?.reduce((s, p) => s + p.count, 0) ?? '—'}</Mono>
      }
      sub={
        series.isPending ? (
          <Skeleton className="h-8" />
        ) : series.isError ? null : (
          <Sparkline data={series.data ?? []} />
        )
      }
    />
  )
}

export function Overview() {
  const navigate = useNavigate()
  const overview = useStatsOverview()
  const timeseries = useIngestionTimeseries(14, 'day')
  const jobs = useJobs(10)
  const health = useHealth()
  const messenger = useMessenger()
  const sourcesRollup = useSourcesRollup()
  const [openItem, setOpenItem] = useState<Item | null>(null)

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

  const metrics = data.metrics
  const p0Active = data.items.by_priority.P0 ?? 0
  const ingestionRate = metrics?.ingestion_success_rate

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Overview</h1>

      {/* --- Hero region (spec §8): attention header, HOT FEED, INITIATE
          TRIAGE CTA, ingestion-success-rate tile, signal velocity, topology.
          Each widget fails soft; the page-level gates above still apply. --- */}
      <section aria-label="Mission control hero" className="space-y-4">
        <div
          data-testid="attention-header"
          className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border bg-card p-4"
        >
          <span className="font-mono text-xs uppercase tracking-wide text-muted-foreground">
            Attention Required
          </span>
          <span className="flex items-center gap-2">
            <Badge variant="p0">P0</Badge>
            <Mono className="text-lg font-bold">{p0Active}</Mono>
            <span className="text-sm text-muted-foreground">active</span>
          </span>
          <span className="flex items-center gap-2">
            <Mono className="text-lg font-bold">{data.pending_triage}</Mono>
            <span className="text-sm text-muted-foreground">pending triage</span>
          </span>
          <a
            data-testid="initiate-triage"
            href="/triage"
            onClick={(e) => {
              e.preventDefault()
              navigate('/triage')
            }}
            className="ml-auto rounded bg-primary px-3 py-1.5 font-mono text-xs font-semibold uppercase tracking-wide text-primary-foreground"
          >
            Initiate Triage ({data.pending_triage})
          </a>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <HotFeed onOpen={setOpenItem} />
          <TopologyPanel />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-1">
            <div data-testid="ingestion-success-tile">
              <StatCard
                label="Ingestion Success Rate (7d)"
                value={<Mono>{pct(ingestionRate)}</Mono>}
              />
            </div>
            <SignalVelocityTile />
          </div>
        </div>
      </section>

      {/* Signal Flow — animated Sankey: sources → WorkBench → outputs */}
      <Card data-testid="signal-flow-card">
        <CardHeader className="flex flex-row items-baseline justify-between pb-2">
          <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Signal Flow
          </CardTitle>
          <span className="font-mono text-xs text-muted-foreground">
            sources → workbench → outputs · hover to isolate
          </span>
        </CardHeader>
        <CardContent>
          <SourceFlow
            data={
              sourcesRollup.data
                ? buildFlowMatrix(
                    Object.fromEntries(
                      sourcesRollup.data.map((s) => [s.adapter_type, s.items_stored]),
                    ),
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
            error={
              sourcesRollup.isError
                ? (sourcesRollup.error as Error).message
                : undefined
            }
            onNavigate={navigate}
          />
        </CardContent>
      </Card>

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

      <div data-testid="stat-grid" className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
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
              <CartesianGrid stroke={CHART_DEFAULTS.grid.stroke} strokeDasharray={CHART_DEFAULTS.grid.strokeDasharray} />
              <XAxis dataKey="date" tickFormatter={(d) => relativeTime(d)} stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <YAxis allowDecimals={false} stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} />
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
              <CartesianGrid stroke={CHART_DEFAULTS.grid.stroke} strokeDasharray={CHART_DEFAULTS.grid.strokeDasharray} />
              <XAxis dataKey="name" stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <YAxis allowDecimals={false} stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} cursor={{ fill: 'transparent' }} />
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
              <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Items by Category"
          empty={categoryData.every((d) => d.value === 0)}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={categoryData} layout="vertical">
              <CartesianGrid stroke={CHART_DEFAULTS.grid.stroke} strokeDasharray={CHART_DEFAULTS.grid.strokeDasharray} />
              <XAxis type="number" allowDecimals={false} stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <YAxis type="category" dataKey="name" width={110} stroke={CHART_DEFAULTS.axis.stroke} fontSize={CHART_DEFAULTS.axis.fontSize} />
              <Tooltip contentStyle={TOOLTIP_CONTENT_STYLE} cursor={{ fill: 'transparent' }} />
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

      {/* Item funnel dialog — canonical mounting: page holds state, dialog
          renders at page root with open/onClose. Triggered by Hot Feed items. */}
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
