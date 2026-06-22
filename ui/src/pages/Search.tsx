// Search page — type-to-search interface that opens items in a dialog.

import { useState, useEffect, useMemo, useRef } from 'react'
import { Search as SearchIcon, X } from 'lucide-react'
import type { SearchItem } from '@/lib/types/search'
import { useItemsSearch } from '@/hooks/useItemDetail'
import { useItemDialog } from '@/hooks/useItemDialog'
import { ApiError } from '@/lib/api'
import { ResultRow } from '@/components/search/ResultRow'
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

const KINDS: Array<[string, string]> = [
  ['all', 'All'],
  ['diff', 'Diffs'],
  ['meta_tasks', 'Tasks'],
  ['google_docs', 'Docs'],
]

export function Search() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('all')
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQ = useDebouncedValue(q.trim(), 250)
  const searchQ = useItemsSearch(debouncedQ)
  const { openItem } = useItemDialog()

  const allItems: SearchItem[] = searchQ.data ?? []
  const filtered = useMemo(
    () => allItems.filter((it) => kind === 'all' || it.kind === kind),
    [allItems, kind],
  )

  const tooShort = debouncedQ.length < 2

  return (
    <div className="grid gap-4" data-testid="search-page">
      <div className="grid gap-1">
        <h1 className="text-lg font-semibold">Search</h1>
        <p className="m-0 text-[13px] text-muted-foreground">
          Every ingested item — click one to inspect its full detail.
        </p>
      </div>

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

      {tooShort ? (
        <EmptyState message="// type at least 2 characters to search" />
      ) : searchQ.isPending ? (
        <div className="grid gap-2" data-testid="search-loading">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : searchQ.isError ? (
        <div role="alert" data-testid="search-error" className="p-6 text-destructive">
          {searchQ.error instanceof ApiError && searchQ.error.status === 401
            ? 'token unavailable; check tunnel/binding'
            : `Failed to load items: ${searchQ.error instanceof ApiError ? searchQ.error.message : 'Unknown error'}`}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState message="// No items match your search" />
      ) : (
        <div role="listbox" aria-label="Search results" className="grid gap-2">
          {filtered.map((it) => (
            <ResultRow
              key={it.id}
              id={`search-row-${it.id}`}
              item={it}
              active={false}
              onClick={() => openItem(it.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
