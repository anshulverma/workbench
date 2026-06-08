// Single-card detail hook for the Triage Card Detail View (#/triage/:cardId).
// apiGet, reuses the five-state pattern, does NOT poll.
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import type { TriageCard } from '@/hooks/useTriage'

export function useTriageCard(id: string) {
  return useQuery({
    queryKey: ['triage', 'card', id],
    queryFn: () => apiGet<TriageCard>(`/api/triage/cards/${id}`),
    enabled: !!id,
  })
}
