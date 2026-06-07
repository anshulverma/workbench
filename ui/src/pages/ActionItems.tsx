// Action Items page (spec Design Section 2.3).
//
// Migrates the legacy ActionList/ActionItem behavior onto TanStack Query and the
// shared DataTable. Lists action items grouped by category against
// GET /api/actions with a category filter, and exposes the three lifecycle
// controls: mark-done (POST /done), change-priority (POST /priority, native
// <select> so it works under jsdom), and snooze (POST /snooze). Implements the
// five UI states (loading / error w/ X-Request-ID / unauthorized / empty /
// normal). Each mutation invalidates ['actions'] and toasts via the hooks.

import { useState } from 'react'
import {
  useActions,
  useChangePriority,
  useMarkDone,
  useSnooze,
  type Action,
} from '@/hooks/useActions'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
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

const priorityClasses: Record<string, string> = {
  P0: 'text-red-600 font-semibold',
  P1: 'text-orange-600 font-semibold',
  P2: 'text-blue-600 font-semibold',
  P3: 'text-muted-foreground font-semibold',
}

export function ActionItems() {
  const [filter, setFilter] = useState('')
  const actions = useActions(filter || undefined)
  const markDone = useMarkDone()
  const changePriority = useChangePriority()
  const snooze = useSnooze()

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

  const rows = Object.values(actions.data.categories).flat()

  const columns: Column<Action>[] = [
    {
      key: 'priority',
      header: 'Priority',
      render: (r) => (
        <span className={priorityClasses[r.priority] ?? 'font-semibold'}>
          {r.priority}
        </span>
      ),
    },
    {
      key: 'summary',
      header: 'Summary',
      render: (r) => (
        <div>
          <span>{r.summary}</span>
          {r.parent_item && (
            <span className="ml-2 text-xs text-muted-foreground">
              from {r.parent_item.summary}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      render: (r) => r.action_category ?? 'uncategorized',
    },
    {
      key: 'age',
      header: 'Age',
      render: (r) => relativeTime(r.created_at),
    },
    {
      key: 'set-priority',
      header: 'Set priority',
      render: (r) => (
        <select
          aria-label={`Set priority for ${r.id}`}
          value={r.priority}
          onChange={(e) =>
            changePriority.mutate({ id: r.id, priority: e.target.value })
          }
          className="rounded border border-input bg-transparent px-2 py-1 text-sm"
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (r) => (
        <div className="flex gap-2">
          <Button
            size="sm"
            aria-label={`Mark ${r.id} done`}
            onClick={() => markDone.mutate(r.id)}
          >
            Done
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Snooze ${r.id}`}
            onClick={() => snooze.mutate({ id: r.id, hours: 4 })}
          >
            Snooze 4h
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">
          Action Items ({actions.data.total})
        </h1>
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

      {rows.length === 0 ? (
        <EmptyState message="No action items. You are all caught up." />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      )}
    </div>
  )
}
