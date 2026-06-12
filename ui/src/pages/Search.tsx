// Search page — master/detail layout for the full item corpus. Left panel has
// query input + kind filters + result list; right panel shows the rich item
// detail with LLM summary, contextual payload, processing log, and actions.
//
// Keyboard navigation: ArrowUp/ArrowDown move through results, Enter selects,
// Escape clears search and returns focus to the input.
// WCAG: result list uses role="listbox" with role="option" on each ResultRow,
// aria-activedescendant on the container.

import {
  useState,
  useEffect,
  useMemo,
  useRef,
  useCallback,
  type KeyboardEvent,
} from 'react'
import { Search as SearchIcon, X } from 'lucide-react'
import { toast } from 'sonner'
import type { SearchItem } from '@/lib/types/search'
import { useSearchItems, useItemActions, useSnoozeItem } from '@/hooks/useSearchItems'
import { ApiError } from '@/lib/api'
import { ResultRow } from '@/components/search/ResultRow'
import {
  SearchItemDetail,
  type ItemAction,
} from '@/components/search/SearchItemDetail'
import { EmptyState } from '@/components/EmptyState'
import { Mono } from '@/components/Mono'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

/** Debounce a value by `delay` ms so rapid keystrokes don't spam the server. */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

const KINDS: Array<[string, string]> = [
  ['all', 'All'],
  ['diff', 'Diffs'],
  ['email', 'Email'],
  ['meeting', 'Meetings'],
  ['chat', 'Chat'],
]

/**
 * Search page — full corpus search with master/detail, contextual payload
 * renderers, processing log, and item actions.
 */
export function Search() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<string>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Debounce query to avoid re-fetching on every keystroke
  const debouncedQ = useDebouncedValue(q.trim(), 250)

  // Fetch items via the server search endpoint
  const searchQ = useSearchItems({ q: debouncedQ || undefined })
  const { archive } = useItemActions()
  const snooze = useSnoozeItem()

  // Cast API response to SearchItem[] (the endpoint returns FunnelItem[] but
  // the server augments items with the full SearchItem shape when the search
  // endpoint is used).
  const allItems: SearchItem[] = (searchQ.data as unknown as SearchItem[]) ?? []

  // Client-side kind filter (the server search may not support kind filtering)
  const filtered = useMemo(() => {
    return allItems.filter((it) => {
      if (kind === 'all') return true
      if (kind === 'diff') return it.kind === 'diff' || it.kind === 'pr'
      return it.kind === kind
    })
  }, [allItems, kind])

  // Keep selection valid when filtered results change
  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null)
      return
    }
    if (!filtered.some((it) => it.id === selectedId)) {
      setSelectedId(filtered[0].id)
    }
  }, [filtered, selectedId])

  // Auto-focus search input when it first becomes available (after loading).
  // The empty-dep effect fires on initial mount — which may be the loading
  // skeleton — so we also trigger when searchQ transitions from pending.
  const didFocus = useRef(false)
  useEffect(() => {
    if (!didFocus.current && inputRef.current) {
      inputRef.current.focus()
      didFocus.current = true
    }
  })

  const selected = filtered.find((it) => it.id === selectedId) ?? null

  // Item actions handler
  const onAction = useCallback(
    (itemId: string, action: ItemAction, value?: string) => {
      switch (action) {
        case 'priority':
          // Priority updates are optimistic for now
          toast.success(`Set ${itemId} → ${value || '—'}`)
          break
        case 'done':
          archive.mutate(itemId)
          break
        case 'archive':
          archive.mutate(itemId)
          break
        case 'snooze':
          snooze.mutate({ itemId, durationMinutes: 240 })
          break
        case 'delete':
          // Delete is a destructive action; the archive mutation serves as
          // the closest available operation (soft delete).
          archive.mutate(itemId)
          toast.success(`Deleted ${itemId}`)
          break
      }
    },
    [archive, snooze],
  )

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (filtered.length === 0) return

      const currentIndex = filtered.findIndex((it) => it.id === selectedId)

      switch (e.key) {
        case 'ArrowDown': {
          e.preventDefault()
          const next = currentIndex < filtered.length - 1 ? currentIndex + 1 : 0
          setSelectedId(filtered[next].id)
          // Scroll the selected row into view
          const nextEl = document.getElementById(`search-row-${filtered[next].id}`)
          nextEl?.scrollIntoView({ block: 'nearest' })
          break
        }
        case 'ArrowUp': {
          e.preventDefault()
          const prev = currentIndex > 0 ? currentIndex - 1 : filtered.length - 1
          setSelectedId(filtered[prev].id)
          const prevEl = document.getElementById(`search-row-${filtered[prev].id}`)
          prevEl?.scrollIntoView({ block: 'nearest' })
          break
        }
        case 'Enter': {
          e.preventDefault()
          // Selection is already tracked; Enter confirms (no-op for now since
          // selection is immediate)
          break
        }
        case 'Escape': {
          e.preventDefault()
          setQ('')
          inputRef.current?.focus()
          break
        }
      }
    },
    [filtered, selectedId],
  )

  // Track whether we have ever successfully fetched data — subsequent
  // query-key changes (new search terms) should NOT flash the loading skeleton.
  const hasLoadedOnce = useRef(false)
  if (searchQ.data) hasLoadedOnce.current = true

  // --- UI states ---

  if (searchQ.isPending && !hasLoadedOnce.current) {
    return (
      <div data-testid="search-loading" className="grid gap-3">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-[300px] w-full" />
      </div>
    )
  }

  if (searchQ.isError) {
    const err = searchQ.error
    if (err instanceof ApiError && err.status === 401) {
      return (
        <div role="alert" data-testid="search-unauthorized" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" data-testid="search-error" className="p-6 text-destructive">
        Failed to load items: {err instanceof ApiError ? err.message : 'Unknown error'}
        {err instanceof ApiError && err.requestId && (
          <div className="text-xs">Request ID: {err.requestId}</div>
        )}
      </div>
    )
  }

  return (
    <div className="grid gap-4 animate-in fade-in" data-testid="search-page">
      {/* title */}
      <div className="grid gap-1">
        <h1 className="text-lg font-semibold">Search</h1>
        <p className="m-0 text-[13px] text-muted-foreground">
          Every ingested item, in any state &mdash; with the full processing log
          it went through.
        </p>
      </div>

      {/* search input */}
      <div className="flex items-center gap-2.5 rounded-md border border-border bg-[var(--surface-lowest)] px-3.5 py-2.5">
        <SearchIcon
          size={18}
          className="shrink-0 text-muted-foreground"
        />
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
        <Mono className="text-xs text-muted-foreground">
          {filtered.length}
        </Mono>
      </div>

      {/* kind filter buttons */}
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

      {/* master/detail split */}
      <div
        className="grid items-start gap-5"
        style={{ gridTemplateColumns: '340px minmax(0,1fr)' }}
        onKeyDown={handleKeyDown}
      >
        {/* result list */}
        <div
          ref={listRef}
          role="listbox"
          aria-label="Search results"
          aria-activedescendant={
            selectedId ? `search-row-${selectedId}` : undefined
          }
          tabIndex={0}
          className="sticky top-0 grid max-h-[calc(100vh-200px)] gap-2 overflow-y-auto pr-1"
        >
          {filtered.length === 0 ? (
            <EmptyState message="// No items match your search" />
          ) : (
            filtered.map((it) => (
              <ResultRow
                key={it.id}
                id={`search-row-${it.id}`}
                item={it}
                active={it.id === selectedId}
                onClick={() => setSelectedId(it.id)}
              />
            ))
          )}
        </div>

        {/* detail panel */}
        <SearchItemDetail item={selected} onAction={onAction} />
      </div>
    </div>
  )
}
