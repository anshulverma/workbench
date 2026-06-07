// Each entry pairs a fill with a foreground that meets WCAG AA contrast against
// that fill (spec 11.3). Amber and the lighter grays use near-black text; the
// darker saturated fills use white.
const COLORS: Record<string, string> = {
  healthy: 'bg-green-600 text-white',
  never_run: 'bg-gray-500 text-white',
  erroring: 'bg-red-600 text-white',
  disabled: 'bg-gray-400 text-gray-900',
  configured: 'bg-green-600 text-white',
  'not-configured': 'bg-amber-500 text-gray-900',
}

export function HealthBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs ${
        COLORS[status] ?? 'bg-gray-500 text-white'
      }`}
    >
      {status}
    </span>
  )
}
