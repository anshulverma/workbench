import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Breadcrumb — back navigation. Hidden at "/". Shows "< Overview" on most
 * pages; shows "< Triage" on /triage/* sub-routes.
 */
export function Breadcrumb({ className }: { className?: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const path = location.pathname

  if (path === '/') return null

  let to = '/'
  let label = 'Overview'
  if (path.startsWith('/triage/')) {
    to = '/triage'
    label = 'Triage'
  }

  return (
    <button
      onClick={() => navigate(to)}
      aria-label={`Back to ${label}`}
      className={cn(
        'mb-3 inline-flex items-center gap-1.5 border-0 bg-transparent p-0 font-mono text-[11px] uppercase tracking-[.04em] text-muted-foreground hover:text-foreground',
        'cursor-pointer',
        className,
      )}
    >
      <ChevronLeft size={13} /> {label}
    </button>
  )
}
