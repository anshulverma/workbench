import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

const badgeVariants = cva(
  'inline-flex items-center rounded-sm border px-2.5 py-0.5 font-mono text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground shadow hover:bg-primary/80',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80',
        outline: 'text-foreground',
        // Priority variants (P0–P3) harmonized with the `.prio-*` classes in
        // index.css and the contrast contract (ADR 0046). P0 = tinted red bg +
        // solid red border + AA-safe peach-red text; lower priorities step down
        // in urgency. Text colors stay AA against their tints.
        p0: 'border-[#ffb4ab] bg-[#93000a]/15 text-[#ffb4ab]',
        p1: 'border-[#ff6a2b] bg-[#ff6a2b]/15 text-[#ff6a2b]',
        p2: 'border-[#71d2ff] bg-[#71d2ff]/15 text-[#71d2ff]',
        p3: 'border-border bg-[#353438]/40 text-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  /**
   * When true, prefix the badge content with "est" and wrap in a tooltip
   * explaining the priority is model-estimated, not user-set.
   */
  estimated?: boolean
}

function Badge({ className, variant, estimated, children, ...props }: BadgeProps) {
  const inner = (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {estimated && (
        <span className="mr-1 font-normal opacity-80">est</span>
      )}
      {children}
    </div>
  )

  if (!estimated) return inner

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>{inner}</TooltipTrigger>
        <TooltipContent>
          Estimated priority — model-scored from relevance + urgency signals, not user-set
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export { Badge, badgeVariants }
