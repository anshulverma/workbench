// Knowledge page — preference facts + Fact Curation (spec Design Section 2.7).
//
// Reads GET /api/memory/facts (always 200) and renders a flat facts list with a
// client-side text search box and a group-by-source toggle. Each fact has edit
// (Dialog + textarea) and delete (confirm Dialog) controls (see FactRow). v1
// shows flat facts only — no entity/relationship graph.
//
// Three distinct empty/degraded states from the envelope:
//   (a) memory_type==="noop"                       -> "Memory layer not enabled"
//   (b) available===false && memory_type!=="noop"  -> "Memory service unreachable" + X-Request-ID
//   (c) available===true && facts.length===0       -> "No preference facts learned yet"
// Plus the standard loading / error (w/ X-Request-ID) / unauthorized states.
// When the memory layer is noop, curation actions are disabled.

import { useMemo, useState } from 'react'
import { useFacts, type Fact } from '@/hooks/useFacts'
import { FactRow } from '@/components/FactRow'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
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

export function Knowledge() {
  const facts = useFacts()
  const [search, setSearch] = useState('')
  const [grouped, setGrouped] = useState(false)

  const filtered = useMemo(() => {
    const all = facts.data?.facts ?? []
    const q = search.trim().toLowerCase()
    if (!q) return all
    return all.filter(
      (f) =>
        f.content.toLowerCase().includes(q) ||
        f.source.toLowerCase().includes(q),
    )
  }, [facts.data, search])

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

  // (c) Configured and reachable but no facts learned yet.
  if (env.facts.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Knowledge</h1>
        <EmptyState message="No preference facts learned yet" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Knowledge</h1>

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
              <ul>
                {group.map((f) => (
                  <FactRow key={f.id} fact={f} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <ul>
          {filtered.map((f) => (
            <FactRow key={f.id} fact={f} />
          ))}
        </ul>
      )}
    </div>
  )
}
