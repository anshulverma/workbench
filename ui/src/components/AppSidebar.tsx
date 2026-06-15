import {
  Activity,
  BookOpen,
  CircleCheckBig,
  LayoutDashboard,
  ListChecks,
  Search,
  Settings,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

// Icon-per-route map (spec §3, ADR0036). Order is the rail's Tab order.
// V3 restructure: Sources + Messenger removed, Search added at position 2.
const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/triage', label: 'Triage', icon: ListChecks },
  { to: '/actions', label: 'Action Items', icon: CircleCheckBig },
  { to: '/ingestion', label: 'Ingestion', icon: Workflow },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/system', label: 'System Status', icon: Activity },
]

/** Check if a route matches a nav item. */
function isRouteActive(to: string, pathname: string): boolean {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(to + '/')
}

/**
 * AppSidebar — 64px icon rail with hover-expand (spec §3, ADR0036).
 *
 * Collapsed: 64px icon-only rail. Hovered: expands to 216px showing labels.
 * CSS transition via `wb-rail-nav` class; labels fade in via `wb-rail-label`.
 *
 * A logo button at the top links to home. lucide 20px icons, one per route.
 * Active item gets a 2px orange left bar + orange icon (`text-primary` is
 * AA-safe on this dark base surface per the contrast contract §13). NavLink
 * preserves HashRouter routing and the `aria-current="page"` marker asserted
 * by a11y.test. Each link carries an `aria-label` plus a Radix tooltip
 * (visible only when rail is collapsed). Hover/active transitions are gated
 * behind `motion-reduce`.
 */
export function AppSidebar({ className }: { className?: string }) {
  const { pathname } = useLocation()

  return (
    <nav
      aria-label="Primary"
      className={cn('wb-rail-nav', className)}
    >
      {/* Logo button */}
      <NavLink
        to="/"
        aria-label="WorkBench home"
        className="relative mb-3 flex h-11 w-full items-center text-foreground"
      >
        <span className="flex w-16 min-w-[64px] items-center justify-center">
          <img src={`${import.meta.env.BASE_URL}wb-icon.svg`} alt="" width={34} height={34} />
        </span>
        <span className="wb-rail-label font-display text-sm font-semibold tracking-tight">
          <span className="text-foreground">Work</span>
          <span className="text-primary">Bench</span>
        </span>
      </NavLink>

      <TooltipProvider delayDuration={200}>
        <ul className="flex flex-col items-stretch gap-1">
          {NAV.map((n) => {
            const Icon = n.icon
            const active = isRouteActive(n.to, pathname)
            return (
              <li key={n.to}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <NavLink
                      to={n.to}
                      end={n.to === '/'}
                      aria-label={n.label}
                      className={cn(
                        'relative flex h-11 w-full items-center text-muted-foreground',
                        'transition-colors hover:bg-accent hover:text-foreground',
                        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ring',
                        'motion-reduce:transition-none',
                        active && 'text-primary hover:text-primary',
                      )}
                    >
                      {active && (
                        <span
                          aria-hidden="true"
                          className="absolute left-0 top-2 bottom-2 w-0.5 rounded-sm bg-primary"
                        />
                      )}
                      <span className="flex w-16 min-w-[64px] items-center justify-center">
                        <Icon className="size-5" aria-hidden="true" />
                      </span>
                      <span className="wb-rail-label text-[13px]">
                        {n.label}
                      </span>
                    </NavLink>
                  </TooltipTrigger>
                  <TooltipContent side="right">{n.label}</TooltipContent>
                </Tooltip>
              </li>
            )
          })}
        </ul>
      </TooltipProvider>
    </nav>
  )
}
