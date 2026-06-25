// PreFilterDialog — the RuleBuilder scoped to pre-extraction: Drop-only, only
// pre-extraction fields available, and a banner reminding the user these drops
// happen before any LLM call (so they're free).

import { Filter, Zap } from 'lucide-react'
import type { ConditionTree } from '@/lib/types/pipeline'
import { RuleBuilderDialog } from './RuleBuilderDialog'

export interface PreFilterDialogProps {
  initialTree?: ConditionTree
  onClose: () => void
  onSave?: (tree: ConditionTree) => void
  errors?: Set<string>
  bodyMax?: string
}

export function PreFilterDialog({ initialTree, onClose, onSave, errors, bodyMax }: PreFilterDialogProps) {
  return (
    <RuleBuilderDialog
      initialTree={initialTree}
      action="drop"
      actionOptions={[{ value: 'drop', label: 'Drop' }]}
      segment="pre"
      title="Pre-filter"
      kicker="PRE_EXTRACTION.FILTER"
      icon={Filter}
      tone="var(--brand)"
      onClose={onClose}
      onSave={(tree) => onSave?.(tree)}
      errors={errors}
      bodyMax={bodyMax}
      banner={
        <div
          className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-success"
          style={{ background: 'color-mix(in srgb, var(--success) 12%, transparent)' }}
        >
          <Zap size={13} />
          <span style={{ fontSize: 12 }}>Runs before any LLM call — drops here cost nothing.</span>
        </div>
      }
    />
  )
}
