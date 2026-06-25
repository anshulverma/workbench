// EnricherConfigDialog — config for an enricher stage: which provider runs, the
// source scope it applies to, depth + budget (max calls / seconds), and an
// enable toggle. The provider's "adds" chips preview the fields it contributes.

import { useState } from 'react'
import { Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Mono } from '@/components/Mono'
import { PROVIDERS } from '@/lib/pipeline/schema'
import type { PipelineNode } from '@/lib/types/pipeline'
import { Field, PanelShell, PipelineDialog, Segmented } from './DialogShell'

const ENRICH_TONE = '#b79cf7'
const SCOPES = ['all', 'diff', 'task', 'email', 'chat', 'calendar']

export interface EnricherConfigDialogProps {
  node: PipelineNode | null
  mode?: 'edit' | 'create'
  onClose: () => void
  onSave?: (config: Record<string, unknown>, sourceScope: string[], enabled: boolean) => void
  bodyMax?: string
}

export function EnricherConfigDialog({ node, mode = 'edit', onClose, onSave, bodyMax }: EnricherConfigDialogProps) {
  const cfg = (node?.config || {}) as { provider?: string; depth?: string; maxCalls?: number; maxSeconds?: number }
  const [prov, setProv] = useState(cfg.provider || PROVIDERS[0].id)
  const [scope, setScope] = useState<string[]>(node?.source_scope || ['diff'])
  const [depth, setDepth] = useState(cfg.depth || 'shallow')
  const [calls, setCalls] = useState(cfg.maxCalls ?? 3)
  const [secs, setSecs] = useState(cfg.maxSeconds ?? 8)
  const [on, setOn] = useState(node ? node.enabled !== false : true)
  const provObj = PROVIDERS.find((p) => p.id === prov)

  return (
    <PipelineDialog width={460} onClose={onClose}>
      <PanelShell
        icon={Wand2}
        tone={ENRICH_TONE}
        kicker={mode === 'create' ? 'ENRICHER.NEW' : 'ENRICHER.CONFIG'}
        title={mode === 'create' ? 'Add enricher' : node ? node.label : 'Enricher'}
        bodyMax={bodyMax}
        footer={
          <>
            <Mono className="mr-auto text-muted-foreground" style={{ fontSize: 11 }}>
              avg 142ms · 318 calls / 24h
            </Mono>
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onSave?.({ provider: prov, depth, maxCalls: calls, maxSeconds: secs }, scope, on)
                onClose()
              }}
            >
              {mode === 'create' ? 'Add' : 'Save'}
            </Button>
          </>
        }
      >
        <Field label="Provider">
          <Select value={prov} onValueChange={setProv}>
            <SelectTrigger className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {provObj && (
          <div className="flex flex-wrap gap-[5px]">
            {provObj.adds.map((a) => (
              <span
                key={a}
                className="rounded-[var(--radius-chip)] bg-[var(--surface-highest)] px-[7px] py-[2px] font-mono text-muted-foreground"
                style={{ fontSize: 10 }}
              >
                + {a}
              </span>
            ))}
          </div>
        )}
        <Field label="Source scope">
          <div className="flex flex-wrap gap-[5px]">
            {SCOPES.map((s) => {
              const sel = scope.includes(s)
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(sel ? scope.filter((x) => x !== s) : [...scope, s])}
                  className="cursor-pointer rounded-[var(--radius-chip)] px-[9px] py-[3px] font-mono"
                  style={{
                    fontSize: 11,
                    border: `1px solid ${sel ? ENRICH_TONE : 'var(--border)'}`,
                    background: sel ? `color-mix(in srgb, ${ENRICH_TONE} 22%, transparent)` : 'var(--surface-lowest)',
                    color: sel ? 'var(--foreground)' : 'var(--muted-foreground)',
                  }}
                >
                  {s}
                </button>
              )
            })}
          </div>
        </Field>
        <div className="grid items-end gap-3" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>
          <Field label="Depth">
            <Segmented
              value={depth}
              onChange={setDepth}
              options={[
                { value: 'shallow', label: 'Shallow' },
                { value: 'deep', label: 'Deep' },
              ]}
            />
          </Field>
          <Field label="Max calls">
            <Input type="number" mono className="h-8" value={calls} onChange={(e) => setCalls(Number(e.target.value))} />
          </Field>
          <Field label="Max secs">
            <Input type="number" mono className="h-8" value={secs} onChange={(e) => setSecs(Number(e.target.value))} />
          </Field>
        </div>
        <div className="flex items-center justify-between rounded-md border border-border bg-[var(--surface-lowest)] px-3 py-2.5">
          <span className="font-semibold" style={{ fontSize: 13 }}>
            Enabled
          </span>
          <Switch checked={on} onCheckedChange={setOn} aria-label="Enricher enabled" />
        </div>
      </PanelShell>
    </PipelineDialog>
  )
}
