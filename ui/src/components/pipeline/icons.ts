// icons.ts — resolves the data-driven icon-name strings carried by the pipeline
// schema (NODE_META / SINK_META / legend / add-stage menu) to lucide
// components. Components that reference a fixed icon import from lucide directly;
// this map is only for names that arrive as data.

import {
  Ban,
  CircleCheckBig,
  Filter,
  Flag,
  Inbox,
  ListChecks,
  RotateCcw,
  ScanLine,
  SlidersHorizontal,
  Sparkles,
  Wand2,
  type LucideIcon,
} from 'lucide-react'

export const PIPELINE_ICONS: Record<string, LucideIcon> = {
  Inbox,
  Filter,
  ScanLine,
  SlidersHorizontal,
  Sparkles,
  Wand2,
  Flag,
  Ban,
  CircleCheckBig,
  ListChecks,
  RotateCcw,
}

/** Resolve a schema icon name, falling back to Flag for unknown names. */
export function pipelineIcon(name: string): LucideIcon {
  return PIPELINE_ICONS[name] ?? Flag
}
