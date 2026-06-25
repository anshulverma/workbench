// Search page — master/detail. A query + kind-filtered results list on the left,
// and a persistent rich detail panel on the right (LLM summary, contextual
// payload, full processing log, current verdict) for the selected item.
//
// Replaces the earlier list-and-modal version: the row no longer opens the
// ?item= dialog — selection is local and the detail renders inline via the same
// ItemDetailBody the dialog uses. The dialog (ItemDetailDialog) stays mounted at
// app root for the OTHER surfaces that deep-link items by URL (LiveTail, Action
// Items, …); Search simply doesn't route through it.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Search as SearchIcon, X } from 'lucide-react'
import type { SearchItem } from '@/lib/types/search'
import { useItemsSearch, useItemDetail } from '@/hooks/useItemDetail'
import { useItemActions } from '@/hooks/useItemActions'
import { ApiError } from '@/lib/api'
import { ResultRow } from '@/components/search/ResultRow'
import { ItemDetailBody } from '@/components/ItemDetailBody'
import { EmptyState } from '@/components/EmptyState'
import { Mono } from '@/components/Mono'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

function useDebouncedValue<T>(value: T, delay: number): T {
  const [d, setD] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setD(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return d
}

// Type-correct kinds (the previous array used meta_tasks/google_docs, which are
// not members of ItemKind). ItemKind = diff | pr | email | meeting | chat.
const KINDS: Array<[string, string]> = [
  ['all', 'All'],
  ['diff', 'Diffs'],
  ['email', 'Email'],
  ['meeting', 'Meetings'],
  ['chat', 'Chat'],
]

export function Search() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('all')
  const [selId, setSelId] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const debouncedQ = useDebouncedValue(q.trim(), 250)
  const searchQ = useItemsSearch(debouncedQ)
  const detailQ = useItemDetail(selId)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const allItems: SearchItem[] = searchQ.data ?? []
  const filtered = useMemo(
    () =>
      allItems.filter(
        (it) =>
          kind === 'all' ||
          it.kind === kind ||
          (kind === 'diff' && it.kind === 'pr'),
      ),
    [allItems, kind],
  )

  // Keep a valid selection: default to the first result, and re-point if the
  // current selection drops out of the filtered list.
  useEffect(() => {
    if (!filtered.length) {
      setSelId(null)
      return
    }
    if (selId == null || !filtered.some((it) => it.id === selId)) {
      setSelId(filtered[0].id)
    }
  }, [filtered, selId])

  // After done/archive/delete the item leaves the list; advance to the next.
  const onAfterDismiss = (id: number) => {
    const idx = filtered.findIndex((it) => it.id === id)
    const next = filtered[idx + 1] ?? filtered[idx - 1] ?? null
    setSelId(next ? next.id : null)
  }
  const { onAction } = useItemActions({ onAfterDismiss })

  return (
    <div className="grid gap-4" data-testid="search-page">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold">Search</h1>
        <p className="m-0 text-[13px] text-muted-foreground">
          Every ingested item, in any state — with the full processing log it went through.
        </p>
      </div>

      {/* query */}
      <div className="flex items-center gap-2.5 rounded-md border border-border bg-[var(--surface-lowest)] px-3.5 py-2.5">
        <SearchIcon size={18} className="shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search items, IDs, sources, tags…"
          aria-label="Search items"
          className="flex-1 border-0 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground"
        />
        {q && (
          <button
            type="button"
            aria-label="Clear"
            onClick={() => setQ('')}
            className="flex h-6.5 w-6.5 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground"
          >
            <X size={15} />
          </button>
        )}
        <Mono className="text-xs text-muted-foreground">{filtered.length}</Mono>
      </div>

      {/* kind filters */}
      <div className="flex flex-wrap gap-1.5">
        {KINDS.map(([k, label]) => (
          <Button
            key={k}
            size="sm"
            variant={kind === k ? 'default' : 'outline'}
            onClick={() => setKind(k)}
          >
            {label}
          </Button>
        ))}
      </div>

      {/* master / detail */}
      <div className="grid items-start gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        {/* results list */}
        <div
          role="listbox"
          aria-label="Search results"
          className="grid max-h-[calc(100vh-220px)] gap-2 self-start overflow-y-auto pr-1 lg:sticky lg:top-0"
        >
          {searchQ.isPending ? (
            <div className="grid gap-2" data-testid="search-loading">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : searchQ.isError ? (
            <div role="alert" data-testid="search-error" className="p-4 text-destructive">
              {searchQ.error instanceof ApiError && searchQ.error.status === 401
                ? 'token unavailable; check tunnel/binding'
                : `Failed to load items: ${searchQ.error instanceof ApiError ? searchQ.error.message : 'Unknown error'}`}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState message="// No items match your search" />
          ) : (
            filtered.map((it) => (
              <ResultRow
                key={it.id}
                id={`search-row-${it.id}`}
                item={it}
                active={it.id === selId}
                onClick={() => setSelId(it.id)}
              />
            ))
          )}
        </div>

        {/* detail panel */}
        <div className="min-w-0">
          {selId == null ? (
            <div className="flex min-h-[360px] flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border text-muted-foreground">
              <SearchIcon size={22} />
              <p className="m-0 font-mono text-[13px]">
                // select an item to inspect its full processing log
              </p>
            </div>
          ) : detailQ.isPending ? (
            <div className="grid gap-3" data-testid="detail-loading">
              <Skeleton className="h-7 w-48" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : detailQ.isError ? (
            <div role="alert" className="p-6 text-destructive">
              {detailQ.error instanceof ApiError && detailQ.error.status === 404
                ? 'Item not found'
                : `Failed to load item: ${detailQ.error instanceof ApiError ? detailQ.error.message : 'Unknown error'}`}
            </div>
          ) : detailQ.data ? (
            <ItemDetailBody item={detailQ.data} onAction={onAction} />
          ) : null}
        </div>
      </div>
    </div>
  )
}
