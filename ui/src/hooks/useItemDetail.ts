import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import { toSearchItem, type ApiSearchItem } from '@/lib/search-adapter'
import type { SearchItem } from '@/lib/types/search'

const SEARCH_MIN_CHARS = 2

/** Rich detail for one item by integer id; disabled when id is null. */
export function useItemDetail(id: number | null) {
  return useQuery<SearchItem>({
    queryKey: ['item-detail', id],
    queryFn: async () => toSearchItem(await apiGet<ApiSearchItem>(`/api/items/by-id/${id}`)),
    enabled: id != null,
    staleTime: 30_000,
  })
}

/** Rich full-text item search; disabled below 2 chars. */
export function useItemsSearch(q: string, limit = 50) {
  const query = q.trim()
  return useQuery<SearchItem[]>({
    queryKey: ['items-search', { q: query, limit }],
    queryFn: async () => {
      const res = await apiGet<{ results: ApiSearchItem[] }>(
        `/api/items/search?q=${encodeURIComponent(query)}&limit=${limit}`,
      )
      return res.results.map(toSearchItem)
    },
    enabled: query.length >= SEARCH_MIN_CHARS,
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  })
}
