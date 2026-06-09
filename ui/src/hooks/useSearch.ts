// useSearch — GET /api/search for the ⌘K command palette (spec §4, ADR0037).
//
// Returns the grouped envelope {q, groups:{items,actions,sources,facts?},
// truncated}. The query is gated to >=2 chars (the palette shows local nav
// Commands for shorter input, so we never hit the server then). The `facts`
// group is ABSENT (not empty) when the memory layer is degraded — callers
// treat its absence as "facts unavailable", never as an error.

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'

export type SearchKind = 'item' | 'action' | 'source' | 'fact'

export interface SearchHit {
  id: string
  kind: SearchKind
  label: string
  sublabel?: string
  /** Server-supplied destination route (/triage, /, /actions, /sources, /knowledge). */
  route: string
}

export interface SearchGroups {
  items: SearchHit[]
  actions: SearchHit[]
  sources: SearchHit[]
  /** Omitted entirely when the memory layer is degraded (ADR0037). */
  facts?: SearchHit[]
}

export interface SearchResponse {
  q: string
  groups: SearchGroups
  truncated: boolean
}

export const SEARCH_MIN_CHARS = 2

export function useSearch(query: string, limit = 20) {
  const q = query.trim()
  const enabled = q.length >= SEARCH_MIN_CHARS
  return useQuery({
    queryKey: ['search', { q, limit }],
    queryFn: () =>
      apiGet<SearchResponse>(
        `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      ),
    enabled,
    // Keep the prior page's results visible while the next query loads so the
    // list doesn't flash empty between keystrokes.
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  })
}
