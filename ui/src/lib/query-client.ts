import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchIntervalInBackground: false,
      retry: 1,
    },
  },
})

// Pause polling on a hidden tab: refetchInterval functions read this.
export function pollWhenVisible(ms: number) {
  return () => (document.visibilityState === 'visible' ? ms : false)
}
