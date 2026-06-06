const COLORS: Record<string, string> = {
  healthy: 'bg-green-600',
  never_run: 'bg-gray-500',
  erroring: 'bg-red-600',
  disabled: 'bg-gray-400',
  configured: 'bg-green-600',
  'not-configured': 'bg-amber-600',
}

export function HealthBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs text-white ${
        COLORS[status] ?? 'bg-gray-500'
      }`}
    >
      {status}
    </span>
  )
}
