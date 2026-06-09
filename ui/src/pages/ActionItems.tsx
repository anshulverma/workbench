// Action Items page (spec §10).
//
// Replaces the flat DataTable with three priority-bucketed sections
// (ACTIVE NOW / TODAY / LATER), a Throughput card (bar/sparkline +
// efficiency_peak), a Terminal Focus / Work Mode card (client-only localStorage
// toggle, ADR 0042), and an orange FAB that creates a manual Action Item via
// POST /api/actions. Preserves the existing category filter and the three
// lifecycle controls exactly (set-priority <select>, Done, Snooze 4h).
//
// Render-loop safety (per task guardrails): buckets are derived with useMemo
// over the STABLE actions array + a single render-time `now` primitive; no
// effect computes arrays/Sets and feeds them back into setState. Work Mode is
// read once in a useState initializer (in useWorkMode) and synced via a
// storage-event effect with EMPTY deps + cleanup.

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
import { useWorkMode } from '@/hooks/useWorkMode'
import { useMetricsTimeseries, useStatsOverview } from '@/hooks/useStats'
import { StatCard } from '@/components/StatCard'
import { Sparkline } from '@/components/Sparkline'
import { Mono } from '@/components/Mono'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
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

// Left-border accent per priority (spec §10 colored left-border rows). Uses the
// same hue tokens as the Badge priority variants (ADR 0046 contrast contract).
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
 * Bucket an action by priority + age (spec §10):
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

/** Render a 0..1 ratio metric as a whole-number percent, or "n/a" when null. */
function pct(value: number | null | undefined): string {
  return value == null ? 'n/a' : `${Math.round(value * 100)}%`
}

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

function ThroughputCard() {
  const series = useMetricsTimeseries('throughput', 8, 'hour')
  const overview = useStatsOverview()
  const efficiency = overview.data?.metrics?.efficiency_peak

  return (
    <div data-testid="throughput-card">
      <StatCard
        label="Throughput (8h)"
        value={
          overview.isError ? (
            'n/a'
          ) : (
            <Mono>{pct(overview.isPending ? null : efficiency)}</Mono>
          )
        }
        sub={
          series.isPending ? (
            <Skeleton className="h-8" />
          ) : series.isError ? null : (
            <Sparkline data={series.data ?? []} />
          )
        }
      />
    </div>
  )
}

function WorkModeCard({
  workMode,
  setWorkMode,
}: {
  workMode: boolean
  setWorkMode: (next: boolean) => void
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Terminal Focus
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm">
          {workMode ? 'WORK_MODE_ON' : 'WORK_MODE_OFF'}
        </span>
        <Switch
          aria-label="Work Mode"
          checked={workMode}
          onCheckedChange={setWorkMode}
        />
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
  const { workMode, setWorkMode } = useWorkMode()
  const actions = useActions(filter || undefined)
  const markDone = useMarkDone()
  const changePriority = useChangePriority()
  const snooze = useSnooze()

  // STABLE input: the flat list of actions. Derived during render via useMemo
  // keyed on the data reference only — never recomputed into an effect+setState.
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

  // --- Work Mode (ADR 0042): collapse to the top active "vector", hide
  // non-critical widgets, dim chrome. Does NOT mute notifications. ---
  if (workMode) {
    const active = grouped['ACTIVE NOW']
    return (
      <div className="space-y-4 opacity-95">
        <div className="flex items-center gap-3">
          <h1 className="font-mono text-lg font-semibold uppercase tracking-wide">
            Terminal Focus
          </h1>
          <WorkModeCard workMode={workMode} setWorkMode={setWorkMode} />
        </div>
        {active.length === 0 ? (
          <EmptyState message="// Nothing critical — you are clear" />
        ) : (
          <div className="space-y-2">
            {active.map((action) => (
              <ActionRow
                key={action.id}
                action={action}
                onChangePriority={onChangePriority}
                onDone={onDone}
                onSnooze={onSnooze}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

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
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <ThroughputCard />
        <WorkModeCard workMode={workMode} setWorkMode={setWorkMode} />
      </div>

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

      <button
        type="button"
        aria-label="New action"
        onClick={() => setCreateOpen(true)}
        className="fixed bottom-6 right-6 flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
      >
        <Plus className="size-6" />
      </button>

      <CreateActionDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
