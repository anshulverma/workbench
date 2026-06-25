// LlmFilterDialog — config for an llm_filter, with its two stages made explicit:
// SCORING (the prompt → relevance + confidence) and ROUTING (thresholds →
// include / triage / drop). Each stage has its own override toggle so the rubric
// and the cutoffs can be changed independently.

import { useState } from 'react'
import { ArrowRight, Sparkles } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Mono } from '@/components/Mono'
import type { PipelineNode } from '@/lib/types/pipeline'
import { Field, PanelShell, PipelineDialog } from './DialogShell'
import { Button } from '@/components/ui/button'

function ThresholdRow({
  label,
  hint,
  val,
  set,
  on,
}: {
  label: string
  hint: string
  val: number
  set: (n: number) => void
  on: boolean
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="flex items-center gap-2.5">
        <input
          type="range"
          min={0}
          max={100}
          value={val}
          disabled={!on}
          onChange={(e) => set(Number(e.target.value))}
          className="flex-1"
          style={{ accentColor: 'var(--primary)' }}
        />
        <Mono
          className="w-9 text-right font-bold"
          style={{ fontSize: 13, color: on ? 'var(--foreground)' : 'var(--muted-foreground)' }}
        >
          {val}
        </Mono>
      </div>
    </Field>
  )
}

function SectionToggle({
  kicker,
  title,
  sub,
  on,
  set,
}: {
  kicker: string
  title: string
  sub: string
  on: boolean
  set: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-2.5">
      <div className="grid gap-px">
        <span className="font-mono uppercase tracking-[0.07em]" style={{ fontSize: 10, color: 'var(--tertiary)' }}>
          {kicker}
        </span>
        <span className="font-semibold" style={{ fontSize: 13 }}>
          {title}
        </span>
        <span className="text-muted-foreground" style={{ fontSize: 11 }}>
          {sub}
        </span>
      </div>
      <label className="inline-flex shrink-0 items-center gap-[7px] text-muted-foreground" style={{ fontSize: 11 }}>
        {on ? 'override' : 'global'}
        <Switch checked={on} onCheckedChange={set} aria-label={`Override ${title}`} />
      </label>
    </div>
  )
}

export interface LlmFilterDialogProps {
  node: PipelineNode | null
  onClose: () => void
  onSave?: (config: Record<string, unknown>) => void
  bodyMax?: string
}

export function LlmFilterDialog({ node, onClose, onSave, bodyMax }: LlmFilterDialogProps) {
  const cfg = (node?.config || {}) as { include?: number; drop?: number; confidence?: number; prompt?: string }
  const [overThresh, setOverThresh] = useState(false)
  const [overPrompt, setOverPrompt] = useState(false)
  const [inc, setInc] = useState(cfg.include ?? 70)
  const [drop, setDrop] = useState(cfg.drop ?? 30)
  const [conf, setConf] = useState(cfg.confidence ?? 70)
  const [prompt, setPrompt] = useState(cfg.prompt ?? '')

  return (
    <PipelineDialog width={468} onClose={onClose}>
      <PanelShell
        icon={Sparkles}
        tone="var(--tertiary)"
        kicker="LLM.FILTER"
        title={node ? node.label : 'LLM filter'}
        bodyMax={bodyMax}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onSave?.({ include: inc, drop, confidence: conf, ...(overPrompt && prompt ? { prompt } : {}) })
                onClose()
              }}
            >
              Save
            </Button>
          </>
        }
      >
        {/* flow explainer */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-[var(--surface-lowest)] px-[11px] py-2 font-mono text-muted-foreground" style={{ fontSize: 10.5 }}>
          <span style={{ color: 'var(--tertiary)' }}>prompt</span>
          <ArrowRight size={11} /> relevance + confidence
          <ArrowRight size={11} /> <span style={{ color: 'var(--primary)' }}>thresholds</span>
          <ArrowRight size={11} /> include / triage / drop
        </div>

        {/* Stage 1 — scoring */}
        <div className="grid gap-[11px] border-b border-border pb-3.5">
          <SectionToggle
            kicker="STAGE 1 · SCORING"
            title="Relevance prompt"
            sub="how each item is scored (rubric the model uses)"
            on={overPrompt}
            set={setOverPrompt}
          />
          <textarea
            className="wb-textarea font-mono"
            rows={3}
            disabled={!overPrompt}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="// using the global triage prompt — describe what makes an item relevant here to override"
            style={{ fontSize: 12, opacity: overPrompt ? 1 : 0.5 }}
          />
        </div>

        {/* Stage 2 — routing */}
        <div className="grid gap-[11px]">
          <SectionToggle
            kicker="STAGE 2 · ROUTING"
            title="Score thresholds"
            sub="what to do with the score · defaults 70 / 30 / 70"
            on={overThresh}
            set={setOverThresh}
          />
          <ThresholdRow label="Auto-include ≥" val={inc} set={setInc} hint="relevance" on={overThresh} />
          <ThresholdRow label="Auto-drop <" val={drop} set={setDrop} hint="relevance" on={overThresh} />
          <ThresholdRow label="Min confidence" val={conf} set={setConf} hint="else → triage" on={overThresh} />
        </div>
      </PanelShell>
    </PipelineDialog>
  )
}
