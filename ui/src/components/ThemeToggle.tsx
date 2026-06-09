import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { cn } from '@/lib/utils'

/**
 * ThemeToggle — three-state light → dark → system cycle (spec §3, ADR0034).
 *
 * Uses next-themes `useTheme`. The button's `aria-label` always reflects the
 * NEXT theme it will switch to so AT users know what activating it does, and
 * the visible lucide icon reflects the CURRENT theme. The hover/icon transition
 * is gated behind `motion-reduce` per the reduced-motion contract.
 */
const ORDER = ['light', 'dark', 'system'] as const
type ThemeName = (typeof ORDER)[number]

const ICON = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const

const NEXT_LABEL = {
  light: 'Switch to dark theme',
  dark: 'Switch to system theme',
  system: 'Switch to light theme',
} as const

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme()
  // `theme` is undefined until next-themes hydrates; treat that as "system".
  const current: ThemeName = (ORDER as readonly string[]).includes(theme ?? '')
    ? (theme as ThemeName)
    : 'system'
  const Icon = ICON[current]

  const cycle = () => {
    const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]
    setTheme(next)
  }

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={NEXT_LABEL[current]}
      title={NEXT_LABEL[current]}
      className={cn(
        'inline-flex size-9 items-center justify-center rounded-md text-muted-foreground',
        'transition-colors hover:bg-accent hover:text-foreground',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        'motion-reduce:transition-none',
        className,
      )}
    >
      <Icon className="size-5" aria-hidden="true" />
    </button>
  )
}
