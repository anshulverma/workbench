import * as React from 'react'

import { cn } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Tabs — lightweight wrapper styled in the shadcn/ui pattern.       */
/*  No Radix dependency — uses plain HTML + ARIA roles so that the    */
/*  component tree stays the same shape as a Radix Tabs tree and can  */
/*  be swapped to @radix-ui/react-tabs later without API changes.     */
/* ------------------------------------------------------------------ */

interface TabsContextValue {
  value: string
  onValueChange: (v: string) => void
}

const TabsCtx = React.createContext<TabsContextValue | null>(null)

function useTabs() {
  const ctx = React.useContext(TabsCtx)
  if (!ctx) throw new Error('Tabs compound components must be used within <Tabs>')
  return ctx
}

/* ---- root ---- */
interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: string
  defaultValue?: string
  onValueChange?: (v: string) => void
}

const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  ({ className, value: controlledValue, defaultValue = '', onValueChange, children, ...props }, ref) => {
    const [internal, setInternal] = React.useState(defaultValue)
    const value = controlledValue ?? internal
    const change = React.useCallback(
      (v: string) => { setInternal(v); onValueChange?.(v) },
      [onValueChange],
    )
    return (
      <TabsCtx.Provider value={{ value, onValueChange: change }}>
        <div ref={ref} className={cn('', className)} data-tabs="" {...props}>
          {children}
        </div>
      </TabsCtx.Provider>
    )
  },
)
Tabs.displayName = 'Tabs'

/* ---- list ---- */
const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        'inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground',
        className,
      )}
      {...props}
    />
  ),
)
TabsList.displayName = 'TabsList'

/* ---- trigger ---- */
interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, ...props }, ref) => {
    const ctx = useTabs()
    const selected = ctx.value === value
    return (
      <button
        ref={ref}
        role="tab"
        type="button"
        aria-selected={selected}
        data-state={selected ? 'active' : 'inactive'}
        className={cn(
          'inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
          selected
            ? 'bg-background text-foreground shadow'
            : 'hover:bg-background/50 hover:text-foreground',
          className,
        )}
        onClick={() => ctx.onValueChange(value)}
        {...props}
      />
    )
  },
)
TabsTrigger.displayName = 'TabsTrigger'

/* ---- content ---- */
interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, ...props }, ref) => {
    const ctx = useTabs()
    if (ctx.value !== value) return null
    return (
      <div
        ref={ref}
        role="tabpanel"
        data-state="active"
        className={cn(
          'mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          className,
        )}
        {...props}
      />
    )
  },
)
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }
