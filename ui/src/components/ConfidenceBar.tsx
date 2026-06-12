import { Mono } from '@/components/Mono'
import { cn } from '@/lib/utils'

/**
 * ConfidenceBar — progress bar with percentage label.
 * Color thresholds: >=90 success, >=80 primary, else brand.
 */
export function ConfidenceBar({
  value,
  className,
}: {
  value: number
  className?: string
}) {
  const tone =
    value >= 90
      ? 'var(--success)'
      : value >= 80
        ? 'var(--primary)'
        : 'var(--brand)'

  return (
    <div
      className={cn('flex items-center gap-2', className)}
      style={{ minWidth: 120 }}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="flex-1 overflow-hidden rounded-full bg-[var(--surface-lowest)]" style={{ height: 5 }}>
        <div
          className="h-full rounded-full"
          style={{ width: `${value}%`, background: tone }}
        />
      </div>
      <Mono className="text-xs font-bold">{value}%</Mono>
    </div>
  )
}
