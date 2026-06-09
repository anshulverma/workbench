import { Component } from 'react'
import { useLocation } from 'react-router-dom'
import { Command } from 'lucide-react'
import { useHealth } from '@/hooks/useStats'
import { Mono } from '@/components/Mono'
import { ThemeToggle } from '@/components/ThemeToggle'
import { cn } from '@/lib/utils'

/**
 * TopBar — sticky top app bar for the mission-control shell (spec §3, ADR0036).
 *
 * Layout (left → right): brand "W"/Workbench mark, a mono route→context label,
 * a ⌘K command-palette trigger (placeholder — wired by S1), a sync-status
 * indicator derived from `/health`, a three-state ThemeToggle, and a user chip.
 * The design's "Deploy" button is intentionally dropped (spec §3 / Out of Scope).
 */

// Route → mono context label. Longest-prefix wins so nested routes
// (e.g. /triage/:id) inherit the parent surface label.
const ROUTE_LABELS: ReadonlyArray<readonly [string, string]> = [
  ['/triage', 'TRIAGE.QUEUE'],
  ['/actions', 'ACTION_ITEMS.LOG'],
  ['/ingestion', 'INGESTION.OPS'],
  ['/sources', 'SOURCES.CONFIG'],
  ['/knowledge', 'KNOWLEDGE.FACTS'],
  ['/messenger', 'MESSENGER'],
  ['/settings', 'SETTINGS'],
  ['/', 'OVERVIEW'],
]

function contextLabel(pathname: string): string {
  for (const [prefix, label] of ROUTE_LABELS) {
    if (prefix === '/') {
      if (pathname === '/') return label
    } else if (pathname === prefix || pathname.startsWith(prefix + '/')) {
      return label
    }
  }
  return 'OVERVIEW'
}

const SYNC_TONE: Record<string, string> = {
  healthy: 'bg-[#9ad08a]',
  degraded: 'bg-primary',
  unhealthy: 'bg-destructive',
  unknown: 'bg-muted-foreground',
}

function SyncStatusInner() {
  const { data, isError, isLoading } = useHealth()
  const status = isError
    ? 'unhealthy'
    : isLoading || !data
      ? 'unknown'
      : data.status === 'ok' || data.status === 'healthy'
        ? 'healthy'
        : data.status === 'degraded'
          ? 'degraded'
          : 'unhealthy'
  return <SyncDot status={status} />
}

function SyncDot({ status }: { status: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 text-xs text-muted-foreground"
      aria-label={`Sync status: ${status}`}
      role="status"
    >
      <span
        aria-hidden="true"
        className={cn(
          'size-2 rounded-full',
          SYNC_TONE[status] ?? SYNC_TONE.unknown,
        )}
      />
      <Mono className="hidden uppercase sm:inline">{status}</Mono>
    </span>
  )
}

/**
 * Guards the health query: when no QueryClientProvider is mounted (e.g. in
 * isolated shell tests) `useHealth` throws — we fail soft to an "unknown" dot
 * rather than crashing the whole shell.
 */
class SyncStatus extends Component<
  Record<string, never>,
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (this.state.failed) return <SyncDot status="unknown" />
    return <SyncStatusInner />
  }
}

export function TopBar({
  className,
  onOpenCommandPalette,
}: {
  className?: string
  /** Wired by S1 to open the ⌘K command palette. */
  onOpenCommandPalette?: () => void
}) {
  const { pathname } = useLocation()
  const label = contextLabel(pathname)

  return (
    <header
      role="banner"
      className={cn(
        'sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background px-4',
        className,
      )}
    >
      {/* Brand mark */}
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="inline-flex size-7 items-center justify-center rounded-md bg-primary font-display text-sm font-bold text-primary-foreground"
        >
          W
        </span>
        <span className="font-display text-sm font-semibold tracking-tight">
          Workbench
        </span>
      </div>

      {/* Mono route → context label */}
      <Mono className="truncate text-xs uppercase text-muted-foreground">
        {label}
      </Mono>

      {/* ⌘K command-palette trigger (placeholder; S1 wires the palette open). */}
      <button
        type="button"
        data-command-trigger="true"
        onClick={onOpenCommandPalette}
        aria-label="Open command palette"
        className={cn(
          'ml-auto inline-flex items-center gap-2 rounded-md border border-border bg-input px-2.5 py-1.5 text-xs text-muted-foreground',
          'transition-colors hover:border-ring hover:text-foreground',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
          'motion-reduce:transition-none',
        )}
      >
        <Command className="size-3.5" aria-hidden="true" />
        <Mono className="hidden sm:inline">K</Mono>
        <span className="hidden md:inline">Search</span>
      </button>

      <SyncStatus />

      <ThemeToggle />

      {/* User chip */}
      <span
        className="inline-flex size-8 items-center justify-center rounded-full bg-accent text-xs font-medium text-foreground"
        aria-label="Account"
        title="Account"
      >
        WB
      </span>
    </header>
  )
}
