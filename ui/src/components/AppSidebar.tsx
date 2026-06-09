import {
  BookOpen,
  CircleCheckBig,
  Database,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Settings,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
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
const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/triage', label: 'Triage', icon: ListChecks },
  { to: '/actions', label: 'Action Items', icon: CircleCheckBig },
  { to: '/ingestion', label: 'Ingestion', icon: Workflow },
  { to: '/sources', label: 'Sources', icon: Database },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/messenger', label: 'Messenger', icon: MessageSquare },
  { to: '/settings', label: 'Settings', icon: Settings },
]

/**
 * AppSidebar — 64px icon rail (spec §3, ADR0036).
 *
 * lucide 20px icons, one per route. Active item gets a 2px orange left bar +
 * orange icon (`text-primary` is AA-safe on this dark base surface per the
 * contrast contract §13). NavLink preserves HashRouter routing and the
 * `aria-current="page"` marker asserted by a11y.test. Each link carries an
 * `aria-label` (links are icon-only) plus a Radix tooltip showing the label,
 * all under a single TooltipProvider. Hover/active transitions are gated behind
 * `motion-reduce`.
 */
export function AppSidebar({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        'flex w-16 flex-col items-center gap-1 border-r border-border bg-background py-3',
        className,
      )}
    >
      <TooltipProvider delayDuration={200}>
        <ul className="flex flex-col items-center gap-1">
          {NAV.map((n) => {
            const Icon = n.icon
            return (
              <li key={n.to}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <NavLink
                      to={n.to}
                      end={n.to === '/'}
                      aria-label={n.label}
                      className={({ isActive }) =>
                        cn(
                          'relative flex size-11 items-center justify-center rounded-md text-muted-foreground',
                          'transition-colors hover:bg-accent hover:text-foreground',
                          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                          'motion-reduce:transition-none',
                          isActive &&
                            'border-l-2 border-primary text-primary hover:text-primary',
                        )
                      }
                    >
                      <Icon className="size-5" aria-hidden="true" />
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
