import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTheme } from 'next-themes'
import {
  BookOpen,
  CircleCheckBig,
  Database,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Palette,
  Settings,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

import { ApiError } from '@/lib/api'
import {
  useSearch,
  SEARCH_MIN_CHARS,
  type SearchHit,
} from '@/hooks/useSearch'
import { Mono } from '@/components/Mono'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'

/**
 * CommandPalette — the ⌘K command palette (spec §4, ADR0037).
 *
 * Controlled via `open`/`onOpenChange` (the global ⌘K listener + TopBar trigger
 * live in AppShell). Behaviour:
 *   - empty / <2-char query → local nav Commands (8 route jumps + Toggle theme).
 *   - ≥2 chars, debounced 200ms → GET /api/search; groups Items/Actions/Sources/
 *     Facts (Facts omitted when its group is absent = memory degraded).
 *   - five internal states: loading / empty / error (+X-Request-ID) /
 *     unauthorized / degraded(facts-absent); a "truncated" hint when capped.
 *   - selecting a hit → navigate(hit.route) + close; selecting a Command runs it.
 *   - cmdk supplies combobox/listbox roles; Radix Dialog traps + restores focus.
 */

interface NavCommand {
  id: string
  label: string
  icon: LucideIcon
  run: () => void
}

const NAV: ReadonlyArray<{ to: string; label: string; icon: LucideIcon }> = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/triage', label: 'Triage', icon: ListChecks },
  { to: '/actions', label: 'Action Items', icon: CircleCheckBig },
  { to: '/ingestion', label: 'Ingestion', icon: Workflow },
  { to: '/sources', label: 'Sources', icon: Database },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/messenger', label: 'Messenger', icon: MessageSquare },
  { to: '/settings', label: 'Settings', icon: Settings },
]

const GROUP_HEADINGS: ReadonlyArray<[keyof SearchHitGroups, string]> = [
  ['items', 'Items'],
  ['actions', 'Actions'],
  ['sources', 'Sources'],
  ['facts', 'Facts'],
]

type SearchHitGroups = {
  items?: SearchHit[]
  actions?: SearchHit[]
  sources?: SearchHit[]
  facts?: SearchHit[]
}

/** Debounce a value by `delay` ms (used to throttle search keystrokes). */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query, 200)

  // Reset the query each time the palette opens so it never reopens stale.
  useEffect(() => {
    if (open) setQuery('')
  }, [open])

  const commands: NavCommand[] = useMemo(() => {
    const navCommands = NAV.map((n) => ({
      id: `nav:${n.to}`,
      label: n.label,
      icon: n.icon,
      run: () => {
        navigate(n.to)
        onOpenChange(false)
      },
    }))
    const toggleTheme: NavCommand = {
      id: 'cmd:toggle-theme',
      label: 'Toggle theme',
      icon: Palette,
      run: () => {
        setTheme(theme === 'dark' ? 'light' : 'dark')
      },
    }
    return [...navCommands, toggleTheme]
  }, [navigate, onOpenChange, setTheme, theme])

  const trimmed = debouncedQuery.trim()
  const isSearching = trimmed.length >= SEARCH_MIN_CHARS
  const { data, isFetching, isError, error } = useSearch(trimmed)

  const selectHit = (hit: SearchHit) => {
    navigate(hit.route)
    onOpenChange(false)
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Search items, actions, sources, facts… or jump to a page"
      />
      <CommandList>
        {!isSearching ? (
          <CommandGroup heading="Commands">
            {commands.map((c) => {
              const Icon = c.icon
              return (
                <CommandItem key={c.id} value={c.label} onSelect={c.run}>
                  <Icon className="text-muted-foreground" aria-hidden="true" />
                  <span>{c.label}</span>
                </CommandItem>
              )
            })}
          </CommandGroup>
        ) : (
          <SearchResults
            data={data}
            isFetching={isFetching}
            isError={isError}
            error={error}
            onSelect={selectHit}
          />
        )}
      </CommandList>
    </CommandDialog>
  )
}

function SearchResults({
  data,
  isFetching,
  isError,
  error,
  onSelect,
}: {
  data: { groups: SearchHitGroups; truncated: boolean } | undefined
  isFetching: boolean
  isError: boolean
  error: unknown
  onSelect: (hit: SearchHit) => void
}) {
  // Error / unauthorized states take priority over stale data.
  if (isError) {
    const apiErr = error instanceof ApiError ? error : null
    if (apiErr?.status === 401 || apiErr?.status === 403) {
      return (
        <StatusRow>
          Unauthorized — your session token may have expired.
        </StatusRow>
      )
    }
    return (
      <StatusRow tone="error">
        Search failed.
        {apiErr?.requestId ? (
          <>
            {' '}
            <Mono className="text-xs">req {apiErr.requestId}</Mono>
          </>
        ) : null}
      </StatusRow>
    )
  }

  if (!data && isFetching) {
    return <StatusRow>Searching…</StatusRow>
  }

  if (!data) {
    return <StatusRow>Searching…</StatusRow>
  }

  const groups = data.groups
  const hasAnyHit = GROUP_HEADINGS.some(
    ([key]) => (groups[key]?.length ?? 0) > 0,
  )

  if (!hasAnyHit) {
    return <CommandEmpty>No results.</CommandEmpty>
  }

  let firstRendered = false
  return (
    <>
      {GROUP_HEADINGS.map(([key, heading]) => {
        // `facts` absent (undefined) = degraded → omit the section entirely.
        const hits = groups[key]
        if (!hits || hits.length === 0) return null
        const showSeparator = firstRendered
        firstRendered = true
        return (
          <div key={key}>
            {showSeparator ? <CommandSeparator /> : null}
            <CommandGroup heading={heading}>
              {hits.map((hit) => (
                <CommandItem
                  key={`${hit.kind}:${hit.id}`}
                  value={`${hit.kind}:${hit.id}:${hit.label}`}
                  onSelect={() => onSelect(hit)}
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{hit.label}</span>
                    {hit.sublabel ? (
                      <Mono className="truncate text-xs text-muted-foreground">
                        {hit.sublabel}
                      </Mono>
                    ) : null}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </div>
        )
      })}
      {data.truncated ? (
        <p className="px-3 py-2 text-center text-xs text-muted-foreground">
          Results truncated — refine your query to see more.
        </p>
      ) : null}
    </>
  )
}

function StatusRow({
  children,
  tone,
}: {
  children: React.ReactNode
  tone?: 'error'
}) {
  return (
    <p
      className={
        tone === 'error'
          ? 'py-6 text-center text-sm text-destructive-foreground'
          : 'py-6 text-center text-sm text-muted-foreground'
      }
      role={tone === 'error' ? 'alert' : undefined}
    >
      {children}
    </p>
  )
}
