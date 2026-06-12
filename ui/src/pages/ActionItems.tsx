// Action Items page (spec section 10, v3 design upgrade).
//
// Priority-bucketed sections (ACTIVE NOW / TODAY / LATER), a full-width
// MultiLineChart showing incoming actions vs completion rate (12h), a
// conditional Filter Tuning section (from the feedback store), and a
// header-level "New action" button + dialog. Category filter preserved.
//
// Render-loop safety: buckets are derived with useMemo over the STABLE
// actions array + a single render-time `now` primitive; no effect computes
// arrays/Sets and feeds them back into setState.

import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import {
  useActions,
  useChangePriority,
  useCreateAction,
  useMarkDone,
  useSnooze,
  type Action,
} from '@/hooks/useActions'
import { useFeedbackStore } from '@/hooks/useFeedback'
import { useMetricsTimeseries } from '@/hooks/useStats'
import { MultiLineChart } from '@/components/MultiLineChart'
import { FilterTuningCard } from '@/components/FilterTuningCard'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { relativeTime } from '@/lib/format'
import { ApiError } from '@/lib/api'

const PRIORITIES = ['P0', 'P1', 'P2', 'P3']

const CATEGORIES = [
  'delegation',
  'communication',
  'scheduling',
  'review',
  'creation',
  'update',
  'decision',
  'investigation',
]

const PRIORITY_VARIANT: Record<string, 'p0' | 'p1' | 'p2' | 'p3'> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
}

// Left-border accent per priority (spec section 10 colored left-border rows).
// Same hue tokens as the Badge priority variants (ADR 0046 contrast contract).
const PRIORITY_BORDER: Record<string, string> = {
  P0: 'border-l-[#ffb4ab]',
  P1: 'border-l-[#ff6a2b]',
  P2: 'border-l-[#71d2ff]',
  P3: 'border-l-border',
}

const HOUR_MS = 3600_000
const DAY_MS = 24 * HOUR_MS

type Bucket = 'ACTIVE NOW' | 'TODAY' | 'LATER'

/**
 * Bucket an action by priority + age (spec section 10):
 *  - ACTIVE NOW = P0, or (P1 & age < 24h)
 *  - TODAY      = remaining P1, or (P2 & age < 7d)
 *  - LATER      = P3, or anything older/snoozed
 */
function bucketOf(action: Action, now: number): Bucket {
  const ageMs = action.created_at
    ? now - new Date(action.created_at).getTime()
    : Number.POSITIVE_INFINITY
  if (action.priority === 'P0') return 'ACTIVE NOW'
  if (action.priority === 'P1') return ageMs < DAY_MS ? 'ACTIVE NOW' : 'TODAY'
  if (action.priority === 'P2') return ageMs < 7 * DAY_MS ? 'TODAY' : 'LATER'
  return 'LATER'
}

const BUCKET_ORDER: Bucket[] = ['ACTIVE NOW', 'TODAY', 'LATER']

function ActionRow({
  action,
  onChangePriority,
  onDone,
  onSnooze,
}: {
  action: Action
  onChangePriority: (id: string, priority: string) => void
  onDone: (id: string) => void
  onSnooze: (id: string) => void
}) {
  return (
    <div
      data-testid={`action-row-${action.id}`}
      className={`flex items-center gap-3 border-l-2 ${
        PRIORITY_BORDER[action.priority] ?? 'border-l-border'
      } rounded-r border-y border-r border-border bg-card p-3`}
    >
      <Badge variant={PRIORITY_VARIANT[action.priority] ?? 'p3'}>
        {action.priority}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">
          {action.summary}
          {action.parent_item && (
            <span className="ml-2 text-xs text-muted-foreground">
              from {action.parent_item.summary}
            </span>
          )}
        </p>
        <p className="font-mono text-xs text-muted-foreground">
          {action.action_category ?? 'uncategorized'} ·{' '}
          {relativeTime(action.created_at)}
        </p>
      </div>
      <select
        aria-label={`Set priority for ${action.id}`}
        value={action.priority}
        onChange={(e) => onChangePriority(action.id, e.target.value)}
        className="rounded border border-input bg-transparent px-2 py-1 text-sm"
      >
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        aria-label={`Mark ${action.id} done`}
        onClick={() => onDone(action.id)}
      >
        Done
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Snooze ${action.id}`}
        onClick={() => onSnooze(action.id)}
      >
        Snooze 4h
      </Button>
    </div>
  )
}

/** Full-width throughput chart: incoming actions vs completion rate (12h). */
function ThroughputChartCard() {
  const incoming = useMetricsTimeseries('incoming_actions', 12, 'hour')
  const completion = useMetricsTimeseries('completion_rate', 12, 'hour')

  const isPending = incoming.isPending || completion.isPending
  const isError = incoming.isError && completion.isError

  const inData = useMemo(
    () => (incoming.data ?? []).map((p) => p.count),
    [incoming.data],
  )
  const compData = useMemo(
    () => (completion.data ?? []).map((p) => p.count),
    [completion.data],
  )

  const inTotal = inData.reduce((a, b) => a + b, 0)
  const doneTotal = compData.reduce((a, b) => a + b, 0)
  const net = inTotal - doneTotal

  const xLabels = useMemo(() => {
    const len = Math.max(inData.length, compData.length, 1)
    return Array.from({ length: len }, (_, i) => `${len - i}h ago`)
  }, [inData.length, compData.length])

  return (
    <Card data-testid="throughput-chart-card">
      <CardHeader className="flex flex-row items-baseline justify-between pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Throughput (12h)
        </CardTitle>
        {!isPending && !isError && (
          <span className="flex gap-4 font-mono text-xs text-muted-foreground">
            <span>
              <span className="font-bold text-[#ff6a2b]">{inTotal}</span> in
            </span>
            <span>
              <span className="font-bold text-[#9ad08a]">{doneTotal}</span> done
            </span>
            <span>
              net{' '}
              <Mono
                className={`font-bold ${net > 0 ? 'text-[var(--brand)]' : 'text-[var(--success)]'}`}
              >
                {net > 0 ? '+' : ''}
                {net}
              </Mono>
            </span>
          </span>
        )}
      </CardHeader>
      <CardContent>
        {isPending ? (
          <Skeleton className="h-[132px] w-full" />
        ) : isError ? (
          <p className="text-sm text-muted-foreground">
            Unable to load throughput data
          </p>
        ) : (
          <MultiLineChart
            height={132}
            xLabels={xLabels}
            series={[
              { name: 'Incoming actions', color: '#ff6a2b', data: inData },
              { name: 'Completion rate', color: '#9ad08a', data: compData },
            ]}
          />
        )}
      </CardContent>
    </Card>
  )
}

function CreateActionDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [summary, setSummary] = useState('')
  const [priority, setPriority] = useState('P2')
  const [error, setError] = useState<string | null>(null)
  const createAction = useCreateAction()

  function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    createAction.mutate(
      { summary, priority },
      {
        onSuccess: () => {
          setSummary('')
          setPriority('P2')
          onOpenChange(false)
        },
        onError: (err) =>
          setError(
            err instanceof ApiError ? err.message : 'Failed to create action',
          ),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Action Item</DialogTitle>
          <DialogDescription>
            Create a manual action item. It is added to your queue immediately.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="action-summary">Summary</Label>
            <Input
              id="action-summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="action-priority">Priority</Label>
            <select
              id="action-priority"
              aria-label="Priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="flex h-9 w-full rounded-md border border-border bg-[#0e0e11] px-3 py-1 text-sm"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createAction.isPending}>
              Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ActionItems() {
  const [filter, setFilter] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const actions = useActions(filter || undefined)
  const markDone = useMarkDone()
  const changePriority = useChangePriority()
  const snooze = useSnooze()
  const feedback = useFeedbackStore()
  const tuningTasks = feedback.openTasks()

  // STABLE input: the flat list of actions. Derived during render via useMemo
  // keyed on the data reference only -- never recomputed into an effect+setState.
  const rows = useMemo<Action[]>(
    () =>
      actions.data ? Object.values(actions.data.categories).flat() : [],
    [actions.data],
  )

  // `now` captured once per render; buckets derived purely (no setState).
  const grouped = useMemo(() => {
    const now = Date.now()
    const out: Record<Bucket, Action[]> = {
      'ACTIVE NOW': [],
      TODAY: [],
      LATER: [],
    }
    for (const action of rows) out[bucketOf(action, now)].push(action)
    return out
  }, [rows])

  if (actions.isPending) {
    return (
      <div data-testid="actions-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (actions.isError) {
    const err = actions.error as ApiError
    if (err.status === 401) {
      return (
        <div role="alert" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load action items: {err.message}
        {err.requestId && (
          <div className="text-xs">Request ID: {err.requestId}</div>
        )}
      </div>
    )
  }

  const onChangePriority = (id: string, priority: string) =>
    changePriority.mutate({ id, priority })
  const onDone = (id: string) => markDone.mutate(id)
  const onSnooze = (id: string) => snooze.mutate({ id, hours: 4 })

  const total = actions.data.total

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Action Items ({total})</h1>
        <select
          aria-label="Filter by category"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded border border-input bg-transparent px-2 py-1 text-sm"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c.charAt(0).toUpperCase() + c.slice(1)}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          className="ml-auto"
          aria-label="New action"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="mr-1 size-4" />
          New action
        </Button>
      </div>

      {/* Filter Tuning section -- conditional on open tuning tasks */}
      {tuningTasks.length > 0 && (
        <section data-testid="filter-tuning-section" className="space-y-2">
          <h2 className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Filter Tuning ({tuningTasks.length})
          </h2>
          <div className="space-y-2">
            {tuningTasks.map((task) => (
              <FilterTuningCard
                key={task.id}
                task={task}
                onApply={(id) => feedback.autoApply(id)}
                onDismiss={(id) => feedback.dismissTask(id)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Full-width throughput chart */}
      <ThroughputChartCard />

      {rows.length === 0 ? (
        <EmptyState message="No action items. You are all caught up." />
      ) : (
        <div className="space-y-6">
          {BUCKET_ORDER.map((bucket) => {
            const items = grouped[bucket]
            if (items.length === 0) return null
            return (
              <section
                key={bucket}
                aria-label={`${bucket} (${items.length})`}
                className="space-y-2"
              >
                <h2 className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {bucket} ({items.length})
                </h2>
                <div className="space-y-2">
                  {items.map((action) => (
                    <ActionRow
                      key={action.id}
                      action={action}
                      onChangePriority={onChangePriority}
                      onDone={onDone}
                      onSnooze={onSnooze}
                    />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}

      <CreateActionDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
