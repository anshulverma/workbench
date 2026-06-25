// DialogShell — shared chrome for the pipeline config dialogs. PipelineDialog
// mounts a panel inside our shadcn Dialog (overlay, focus-trap, Esc, close
// button); PanelShell is the header/banner/body/footer layout; Field + Segmented
// are the small form controls the dialogs reuse.

import type { CSSProperties, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export function PipelineDialog({
  width = 460,
  onClose,
  children,
}: {
  width?: number
  onClose: () => void
  children: ReactNode
}) {
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        aria-describedby={undefined}
        className="max-w-[95vw] gap-0 overflow-hidden border-border bg-popover p-0 text-popover-foreground"
        style={{ width }}
      >
        {children}
      </DialogContent>
    </Dialog>
  )
}

export function PanelShell({
  icon: Icon,
  tone,
  kicker,
  title,
  banner,
  children,
  footer,
  bodyMax = '62vh',
}: {
  icon?: LucideIcon
  tone?: string
  kicker?: string
  title: string
  banner?: ReactNode
  children: ReactNode
  footer?: ReactNode
  bodyMax?: string
}) {
  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-3.5">
        {Icon && (
          <span
            className="inline-flex h-7 w-7 items-center justify-center rounded-[var(--radius-control)]"
            style={{
              background: `color-mix(in srgb, ${tone || 'var(--primary)'} 16%, transparent)`,
              color: tone || 'var(--primary)',
            }}
          >
            <Icon size={15} />
          </span>
        )}
        <div className="grid min-w-0 flex-1 gap-px pr-6">
          {kicker && (
            <span className="font-mono uppercase tracking-[0.08em] text-muted-foreground" style={{ fontSize: 9.5 }}>
              {kicker}
            </span>
          )}
          <DialogTitle
            className="font-semibold tracking-[-0.01em]"
            style={{ fontFamily: 'var(--font-display)', fontSize: 16 }}
          >
            {title}
          </DialogTitle>
        </div>
      </div>
      {banner}
      <div
        className="grid gap-3.5 p-4"
        style={{ maxHeight: bodyMax, overflowY: bodyMax === 'none' ? 'visible' : 'auto' }}
      >
        {children}
      </div>
      {footer && (
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div>
      )}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="grid gap-[5px]">
      <span className="flex items-baseline gap-2">
        <span className="font-mono uppercase tracking-[0.06em] text-muted-foreground" style={{ fontSize: 10 }}>
          {label}
        </span>
        {hint && (
          <span className="text-muted-foreground opacity-80" style={{ fontSize: 11 }}>
            {hint}
          </span>
        )}
      </span>
      {children}
    </label>
  )
}

export interface SegmentedOption {
  value: string
  label: string
}

export function Segmented({
  value,
  options,
  onChange,
  style,
}: {
  value: string
  options: SegmentedOption[]
  onChange: (v: string) => void
  style?: CSSProperties
}) {
  return (
    <div
      role="group"
      className="inline-flex overflow-hidden rounded-[var(--radius-control)] border border-border bg-[var(--surface-lowest)]"
      style={style}
    >
      {options.map((o) => {
        const on = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              'cursor-pointer border-0 px-[11px] py-[5px] font-mono uppercase tracking-[0.04em]',
              on ? 'bg-primary text-primary-foreground' : 'bg-transparent text-muted-foreground',
            )}
            style={{ fontSize: 11 }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
