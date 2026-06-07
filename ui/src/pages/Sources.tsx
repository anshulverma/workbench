// Sources management page (spec Design Section 2.5).
//
// A DataTable of configured sources (adapter_type, id/label, enabled Switch,
// human-readable schedule w/ cron tooltip, relative last_run, items_ingested,
// Source Health Status badge, and a per-row kebab menu: Edit / Poll now /
// Enable-Disable / Delete). Delete is behind a confirm Dialog. The add/edit
// form is the two-step SourceForm. Implements the five UI states (loading /
// error w/ X-Request-ID / empty / unauthorized / normal).

import { useState } from 'react'
import {
  useSourceStats,
  useToggleSource,
  usePollSource,
  useDeleteSource,
} from '@/hooks/useSources'
import { SourceForm } from '@/components/SourceForm'
import { DataTable, type Column } from '@/components/DataTable'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { relativeTime } from '@/lib/format'
import { ApiError } from '@/lib/api'
import { toast } from 'sonner'
import type { SourceRollup } from '@/hooks/useStats'

// Map common cron presets to a friendly label; fall back to the raw cron.
const SCHEDULE_LABELS: Record<string, string> = {
  '*/15 * * * *': 'Every 15 minutes',
  '0 * * * *': 'Hourly',
  '0 */6 * * *': 'Every 6 hours',
  '0 9 * * *': 'Daily at 9am',
}

function humanSchedule(cron: string | null): string {
  if (!cron) return 'manual'
  return SCHEDULE_LABELS[cron] ?? cron
}

export function Sources() {
  const stats = useSourceStats()
  const toggle = useToggleSource()
  const poll = usePollSource()
  const del = useDeleteSource()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<SourceRollup | null>(null)
  const [pendingDelete, setPendingDelete] = useState<SourceRollup | null>(null)

  if (stats.isPending) {
    return (
      <div data-testid="sources-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (stats.isError) {
    const err = stats.error as ApiError
    if (err.status === 401) {
      return (
        <div role="alert" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load sources: {err.message}
        {err.requestId && (
          <div className="text-xs">Request ID: {err.requestId}</div>
        )}
      </div>
    )
  }

  if (adding) return <SourceForm onDone={() => setAdding(false)} />
  if (editing) {
    return <SourceForm source={editing} onDone={() => setEditing(null)} />
  }

  if (stats.data.length === 0) {
    return (
      <EmptyState
        message="No sources configured"
        cta={
          <Button onClick={() => setAdding(true)}>Add your first source</Button>
        }
      />
    )
  }

  const columns: Column<SourceRollup>[] = [
    { key: 'type', header: 'Adapter', render: (r) => r.adapter_type },
    { key: 'id', header: 'ID', render: (r) => <span className="font-mono text-xs">{r.id}</span> },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (r) => (
        <Switch
          aria-label={`Toggle ${r.id}`}
          checked={r.enabled}
          onCheckedChange={(v) => toggle.mutate({ id: r.id, enabled: v })}
        />
      ),
    },
    {
      key: 'schedule',
      header: 'Schedule',
      render: (r) => (
        <span title={r.schedule ?? undefined}>{humanSchedule(r.schedule)}</span>
      ),
    },
    {
      key: 'last_run',
      header: 'Last run',
      render: (r) => relativeTime(r.last_run),
    },
    {
      key: 'items_stored',
      header: 'Items ingested',
      render: (r) => r.items_stored,
    },
    {
      key: 'health',
      header: 'Source Health',
      render: (r) => <HealthBadge status={r.health_status} />,
    },
    {
      key: 'actions',
      header: '',
      render: (r) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" aria-label={`Actions for ${r.id}`}>
              ⋯
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setEditing(r)}>
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() =>
                poll.mutate(r.id, {
                  onSuccess: () => toast.success('Poll started'),
                  onError: (e) =>
                    toast.error(`Poll failed: ${(e as ApiError).message}`),
                })
              }
            >
              Poll now
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => toggle.mutate({ id: r.id, enabled: !r.enabled })}
            >
              {r.enabled ? 'Disable' : 'Enable'}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive"
              onSelect={() => setPendingDelete(r)}
            >
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Sources</h1>
        <Button onClick={() => setAdding(true)}>Add source</Button>
      </div>
      <DataTable columns={columns} rows={stats.data} rowKey={(r) => r.id} />

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => {
          if (!o) setPendingDelete(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete source?</DialogTitle>
            <DialogDescription>
              {pendingDelete &&
                `This removes ${pendingDelete.adapter_type} (${pendingDelete.id}) from config.yml and stops its poll job. This cannot be undone.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const target = pendingDelete
                setPendingDelete(null)
                if (target) {
                  del.mutate(target.id, {
                    onSuccess: () => toast.success('Source deleted'),
                  })
                }
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
