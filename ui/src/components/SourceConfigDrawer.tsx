// Per-source relevance / noise-filter Config Drawer (spec §11, ADR0044).
//
// A slide-in panel (Radix Dialog → focus trap + a11y) carrying three INTEGER
// 0..100 sliders — auto_include_threshold / triage_threshold / drop_below —
// bound to the source's `relevance`. A null `relevance` inherits the global
// defaults (70/30/30), shown as an "inherited" hint. Save PATCHes
// /api/sources/{id} with the relevance object; an inverted/out-of-range 422 is
// surfaced inline. The card reflects the change after the rollup invalidates
// (hot-reload is server-side, ADR0013).
//
// Render-loop guardrail: slider state is plain useState seeded from props at
// MOUNT only. The parent keys this component on `source.id`, so opening a
// different source remounts it and re-seeds — there is NO effect that re-sets
// state on every render.

import { useState } from 'react'
import {
  RELEVANCE_DEFAULTS,
  useUpdateRelevance,
} from '@/hooks/useSources'
import type { SourceRollup } from '@/hooks/useStats'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Mono } from '@/components/Mono'
import { ApiError } from '@/lib/api'

interface ThresholdSliderProps {
  id: string
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
}

function ThresholdSlider({ id, label, hint, value, onChange }: ThresholdSliderProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <Mono className="text-sm text-muted-foreground">{value}</Mono>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        step={1}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

// Pull the human-readable message out of a 422 body. FastAPI validation errors
// serialize `detail` as a list of {loc, msg}; the SourceRelevanceConfig model's
// ordering errors land there. Fall back to the raw message otherwise.
function relevanceErrorMessage(err: ApiError): string {
  try {
    const detail = JSON.parse(err.message) as
      | { loc?: unknown[]; msg?: string }[]
      | { msg?: string }
      | string
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => d.msg).filter(Boolean)
      if (msgs.length) return msgs.join('; ')
    } else if (typeof detail === 'object' && detail.msg) {
      return detail.msg
    } else if (typeof detail === 'string') {
      return detail
    }
  } catch {
    /* err.message was not JSON */
  }
  return err.message
}

export function SourceConfigDrawer({
  source,
  onClose,
}: {
  source: SourceRollup
  onClose: () => void
}) {
  const inherited = source.relevance == null
  const seed = source.relevance ?? RELEVANCE_DEFAULTS
  const update = useUpdateRelevance()

  // Seeded at mount only (component is keyed on source.id by the parent).
  const [autoInclude, setAutoInclude] = useState(seed.auto_include_threshold)
  const [triage, setTriage] = useState(seed.triage_threshold)
  const [dropBelow, setDropBelow] = useState(seed.drop_below)
  const [error, setError] = useState<string | null>(null)

  const onSave = () => {
    setError(null)
    update.mutate(
      {
        id: source.id,
        relevance: {
          auto_include_threshold: autoInclude,
          triage_threshold: triage,
          drop_below: dropBelow,
        },
      },
      {
        onSuccess: () => onClose(),
        onError: (e) => setError(relevanceErrorMessage(e as ApiError)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="left-auto right-0 top-0 h-full max-w-md translate-x-0 translate-y-0 rounded-none border-l data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:rounded-none"
      >
        <DialogHeader>
          <DialogTitle>Noise filter — {source.adapter_type}</DialogTitle>
          <DialogDescription>
            Relevance thresholds (0–100) route scored items. ≥ auto-include →
            active; &lt; drop-below → dropped as noise; otherwise → triage.
            {inherited && (
              <span className="mt-1 block text-xs">
                Inherited from global defaults (no per-source override yet).
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <ThresholdSlider
            id="auto-include-threshold"
            label="Auto-include threshold"
            hint="Items scoring at or above this go straight to active."
            value={autoInclude}
            onChange={setAutoInclude}
          />
          <ThresholdSlider
            id="triage-threshold"
            label="Triage threshold"
            hint="Lower edge of the triage band (between drop-below and auto-include)."
            value={triage}
            onChange={setTriage}
          />
          <ThresholdSlider
            id="drop-below"
            label="Drop below"
            hint="Items scoring under this are dropped as noise."
            value={dropBelow}
            onChange={setDropBelow}
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={update.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
