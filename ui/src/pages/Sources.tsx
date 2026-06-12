// Sources management page (spec §11, Stitch variant B — card grid).
//
// A card grid of configured real adapters only (github/email/calendar/chat):
// each card shows a HealthBadge (Source Health Status), last sync (last_run), a
// volume sparkline (items_stored), an enable Switch, and a kebab menu
// (Configure / Edit / Poll now / Enable-Disable / Delete). Delete is behind a
// confirm Dialog. A dashed "Connect New Source" card opens the two-step
// SourceForm wizard. Top StatCards summarize Active Pipes (enabled count),
// Ingestion Volume (sum items_stored), and Errors (erroring-source count). The
// per-source Config Drawer (SourceConfigDrawer) edits relevance/noise
// thresholds (ADR0044). Implements the five UI states (loading / error w/
// X-Request-ID / empty / unauthorized / normal).

import { useState } from 'react'
import {
  useSourceStats,
  useToggleSource,
  usePollSource,
  useDeleteSource,
} from '@/hooks/useSources'
import { SourceForm } from '@/components/SourceForm'
import { SourceConfigDrawer } from '@/components/SourceConfigDrawer'
import { HealthBadge } from '@/components/HealthBadge'
import { StatCard } from '@/components/StatCard'
import { Sparkline } from '@/components/Sparkline'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Mono } from '@/components/Mono'
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

export function Sources({ embedded }: { embedded?: boolean } = {}) {
  const stats = useSourceStats()
  const toggle = useToggleSource()
  const poll = usePollSource()
  const del = useDeleteSource()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<SourceRollup | null>(null)
  const [configuring, setConfiguring] = useState<SourceRollup | null>(null)
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

  const rows = stats.data
  const activePipes = rows.filter((r) => r.enabled).length
  const volume = rows.reduce((sum, r) => sum + r.items_stored, 0)
  const errors = rows.filter((r) => r.health_status === 'erroring').length

  return (
    <div className="space-y-4">
      {!embedded && (
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Sources</h1>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div data-testid="stat-active-pipes">
          <StatCard label="Active Pipes" value={activePipes} />
        </div>
        <div data-testid="stat-volume">
          <StatCard label="Ingestion Volume" value={volume} />
        </div>
        <div data-testid="stat-errors">
          <StatCard label="Errors" value={errors} danger={errors > 0} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => (
          <Card key={r.id}>
            <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
              <div className="space-y-1">
                <div className="font-semibold">{r.adapter_type}</div>
                <Mono className="text-xs text-muted-foreground">{r.id}</Mono>
              </div>
              <div className="flex items-center gap-2">
                <HealthBadge status={r.health_status} />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Actions for ${r.id}`}
                    >
                      ⋯
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setConfiguring(r)}>
                      Configure
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setEditing(r)}>
                      Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() =>
                        poll.mutate(r.id, {
                          onSuccess: () => toast.success('Poll started'),
                          onError: (e) =>
                            toast.error(
                              `Poll failed: ${(e as ApiError).message}`,
                            ),
                        })
                      }
                    >
                      Poll now
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() =>
                        toggle.mutate({ id: r.id, enabled: !r.enabled })
                      }
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
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <Sparkline data={[{ count: r.items_stored }]} />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span title={r.schedule ?? undefined}>
                  {humanSchedule(r.schedule)}
                </span>
                <span>Last sync: {relativeTime(r.last_run)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  <Mono>{r.items_stored}</Mono> items
                </span>
                <Switch
                  aria-label={`Toggle ${r.id}`}
                  checked={r.enabled}
                  onCheckedChange={(v) =>
                    toggle.mutate({ id: r.id, enabled: v })
                  }
                />
              </div>
            </CardContent>
          </Card>
        ))}

        {/* Connect New Source — dashed card opens the 2-step wizard. */}
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="flex min-h-[12rem] flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border text-muted-foreground transition-colors hover:border-primary hover:text-primary"
        >
          <span className="text-2xl leading-none">+</span>
          <span className="text-sm font-medium">Connect New Source</span>
        </button>
      </div>

      {configuring && (
        <SourceConfigDrawer
          key={configuring.id}
          source={configuring}
          onClose={() => setConfiguring(null)}
        />
      )}

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
