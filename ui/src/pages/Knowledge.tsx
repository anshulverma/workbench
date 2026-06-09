// Knowledge page — preference facts curation (spec §12, ADR0045).
//
// Top StatCards: Total Facts (facts.length), Active Sources (sources_enabled
// from the stats overview), Growth Velocity (the scalar metrics.growth_velocity;
// "n/a" when null — never fabricated). Below: a facts TABLE (source pill +
// content + created date, em-dash when null) with a client-side text search box,
// a group-by-source toggle, and per-row edit/delete (FactRow, ADR0019
// tombstones). An "Add Fact" button opens a small create dialog that POSTs a
// manual Preference Fact (origin "manual").
//
// Three distinct empty/degraded states from the GET facts envelope:
//   (a) memory_type==="noop"                       -> "Memory layer not enabled"
//   (b) available===false && memory_type!=="noop"  -> "Memory service unreachable" + X-Request-ID
//   (c) available===true && facts.length===0       -> "No preference facts learned yet"
// Plus the standard loading / error (w/ X-Request-ID) / unauthorized states.
// Add Fact is HIDDEN whenever the memory layer is degraded (noop/unreachable),
// since the create call would 501 — we never show an error state for it.

import { useMemo, useState } from 'react'
import { useFacts, useCreateFact, factErrorMessage, type Fact } from '@/hooks/useFacts'
import { useStatsOverview } from '@/hooks/useStats'
import { FactRow } from '@/components/FactRow'
import { StatCard } from '@/components/StatCard'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'

function groupBySource(facts: Fact[]): [string, Fact[]][] {
  const groups = new Map<string, Fact[]>()
  for (const f of facts) {
    const key = f.source || 'unknown'
    const list = groups.get(key)
    if (list) list.push(f)
    else groups.set(key, [f])
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

function FactsTable({ facts }: { facts: Fact[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Source</TableHead>
          <TableHead>Fact</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {facts.map((f) => (
          <FactRow key={f.id} fact={f} />
        ))}
      </TableBody>
    </Table>
  )
}

function AddFactDialog() {
  const create = useCreateFact()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setValue('')
    setError(null)
  }

  function submit() {
    setError(null)
    create.mutate(value, {
      onSuccess: () => {
        setOpen(false)
        reset()
      },
      // Keep the dialog open on failure (e.g. a 422 blank-content rejection) so
      // the user can correct the input; surface the message inline.
      onError: (err) => setError(factErrorMessage(err)),
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) reset()
      }}
    >
      <Button size="sm" onClick={() => setOpen(true)}>
        Add Fact
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a fact</DialogTitle>
          <DialogDescription>
            Manually record a preference fact. It is stored with a distinct
            "manual" origin and is not overwritten by learned facts.
          </DialogDescription>
        </DialogHeader>
        <textarea
          aria-label="New fact content"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={4}
          className="w-full rounded border border-border bg-background p-2"
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setOpen(false)
              reset()
            }}
          >
            Cancel
          </Button>
          <Button disabled={create.isPending} onClick={submit}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Knowledge() {
  const facts = useFacts()
  const stats = useStatsOverview()
  const [search, setSearch] = useState('')
  const [grouped, setGrouped] = useState(false)

  const allFacts = facts.data?.facts ?? []
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return allFacts
    return allFacts.filter(
      (f) =>
        f.content.toLowerCase().includes(q) ||
        f.source.toLowerCase().includes(q),
    )
  }, [allFacts, search])

  if (facts.isPending) {
    return (
      <div data-testid="knowledge-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (facts.isError) {
    const err = facts.error as ApiError
    if (err.status === 401) {
      return (
        <div role="alert" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load facts: {err.message}
        {err.requestId && (
          <div className="text-xs">Request ID: {err.requestId}</div>
        )}
      </div>
    )
  }

  const env = facts.data

  // (a) Noop memory layer: feature not enabled at all.
  if (env.memory_type === 'noop') {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Knowledge</h1>
        <div
          role="status"
          className="rounded border border-amber-600/40 bg-amber-600/10 p-4"
        >
          <p className="font-medium">Memory layer not enabled</p>
          <p className="text-sm text-muted-foreground">
            No memory provider is configured, so no preference facts are learned.
            Configure a memory layer in config.yml to enable fact curation.
          </p>
        </div>
      </div>
    )
  }

  // (b) Configured but unreachable: memory provider is set but not available.
  if (!env.available) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Knowledge</h1>
        <div
          role="status"
          className="rounded border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="font-medium">Memory service unreachable</p>
          <p className="text-sm text-muted-foreground">
            The configured memory layer ({env.memory_type}) is not responding.
          </p>
          {env.requestId && (
            <p className="mt-1 text-xs text-muted-foreground">
              Request ID: {env.requestId}
            </p>
          )}
        </div>
      </div>
    )
  }

  // Growth Velocity is the scalar metrics.growth_velocity from the overview;
  // null (zero-denominator/degraded) renders "n/a", never a fabricated value.
  const growth = stats.data?.metrics?.growth_velocity
  const growthValue = growth == null ? 'n/a' : String(growth)
  const sourcesEnabled =
    stats.data?.sources_enabled == null ? 'n/a' : String(stats.data.sources_enabled)

  const statCards = (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
      <div data-testid="stat-total-facts">
        <StatCard label="Total Facts" value={env.facts.length} />
      </div>
      <div data-testid="stat-active-sources">
        <StatCard label="Active Sources" value={sourcesEnabled} />
      </div>
      <div data-testid="stat-growth-velocity">
        <StatCard label="Growth Velocity" value={growthValue} />
      </div>
    </div>
  )

  // (c) Configured and reachable but no facts learned yet.
  if (env.facts.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Knowledge</h1>
          <AddFactDialog />
        </div>
        {statCards}
        <EmptyState message="No preference facts learned yet" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Knowledge</h1>
        <AddFactDialog />
      </div>

      {statCards}

      <div className="flex flex-wrap items-center gap-4">
        <Input
          aria-label="Search facts"
          placeholder="Search facts…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <label className="flex items-center gap-2 text-sm">
          <Switch
            aria-label="Group by source"
            checked={grouped}
            onCheckedChange={setGrouped}
          />
          Group by source
        </label>
      </div>

      {filtered.length === 0 ? (
        <EmptyState message="No facts match your search" />
      ) : grouped ? (
        <div className="space-y-6">
          {groupBySource(filtered).map(([source, group]) => (
            <section key={source} aria-label={`Source ${source}`}>
              <h2 className="mb-1 text-sm font-semibold text-muted-foreground">
                {source}
              </h2>
              <FactsTable facts={group} />
            </section>
          ))}
        </div>
      ) : (
        <FactsTable facts={filtered} />
      )}
    </div>
  )
}
