// Two-step add/edit source form (spec Design Section 2.5).
//
// Step 1 picks an adapter_type from {github, email, calendar, chat}; Step 2
// renders type-specific fields validated by a zod discriminated union that
// mirrors each provider's ProviderConfig. Google adapters (email/calendar/chat)
// pick a Connection by name and are disabled when none exists; github shows an
// ambient-gh-auth note. Secrets are NEVER typed. Schedule controls offer cron
// presets, an advanced custom-cron field, and a client-side next-run preview
// (cron-parser). Create/edit are pessimistic; server 422 field errors map onto
// the offending form fields. In edit mode adapter_type is immutable.

import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { parseExpression } from 'cron-parser'
import { toast } from 'sonner'
import {
  useAdapterTypes,
  useConnections,
  useCreateSource,
  useEditSource,
  type Connection,
} from '@/hooks/useSources'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import type { SourceRollup } from '@/hooks/useStats'

// --- zod discriminated union: one variant per adapter_type, mirroring the
// backend ProviderConfig fields. List fields are entered comma-separated. ---
const githubSchema = z.object({
  adapter_type: z.literal('github'),
  repos: z.string().min(1, 'enter at least one repo'),
})
const emailSchema = z.object({
  adapter_type: z.literal('email'),
  connection: z.string().min(1, 'select a connection'),
  label_filters: z.string().optional(),
  max_results: z.string().optional(),
})
const calendarSchema = z.object({
  adapter_type: z.literal('calendar'),
  connection: z.string().min(1, 'select a connection'),
  calendar_ids: z.string().optional(),
  lookahead_hours: z.string().optional(),
})
const chatSchema = z.object({
  adapter_type: z.literal('chat'),
  connection: z.string().min(1, 'select a connection'),
  spaces: z.string().optional(),
  exclude_spaces: z.string().optional(),
  track: z.string().optional(),
  user_id: z.string().optional(),
})
const formSchema = z.discriminatedUnion('adapter_type', [
  githubSchema,
  emailSchema,
  calendarSchema,
  chatSchema,
])
type FormValues = z.infer<typeof formSchema>

const GOOGLE_ADAPTERS = new Set(['email', 'calendar', 'chat'])

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: 'Every 15 minutes', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: 'Daily at 9am', cron: '0 9 * * *' },
]

function nextRunPreview(cron: string): string {
  try {
    const next = parseExpression(cron).next().toDate()
    return `Next run: ${next.toLocaleString()}`
  } catch {
    return 'Invalid cron expression'
  }
}

// comma-separated string -> trimmed non-empty list
function toList(raw: unknown): string[] {
  return String(raw ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function listToCsv(v: unknown): string {
  return Array.isArray(v) ? (v as unknown[]).map(String).join(', ') : ''
}

interface SourceFormProps {
  onDone: () => void
  source?: SourceRollup
}

const inputCls =
  'mt-1 block w-full rounded border border-border bg-background p-2'

export function SourceForm({ onDone, source }: SourceFormProps) {
  const editing = source !== undefined
  const adapterTypes = useAdapterTypes()
  const connections = useConnections()
  const create = useCreateSource()
  const edit = useEditSource()
  const [picked, setPicked] = useState<string | null>(
    editing ? source!.adapter_type : null,
  )
  const [schedule, setSchedule] = useState<string>(
    editing ? source!.schedule ?? CRON_PRESETS[0].cron : CRON_PRESETS[0].cron,
  )
  const [advanced, setAdvanced] = useState(false)

  // Prefill the type-specific fields from the existing config in edit mode.
  const cfg = (source?.config ?? {}) as Record<string, unknown>
  const defaults = useMemo(
    () => ({
      repos: listToCsv(cfg.repos),
      label_filters: listToCsv(cfg.label_filters),
      max_results: cfg.max_results !== undefined ? String(cfg.max_results) : '',
      calendar_ids: listToCsv(cfg.calendar_ids),
      lookahead_hours:
        cfg.lookahead_hours !== undefined ? String(cfg.lookahead_hours) : '',
      spaces: listToCsv(cfg.spaces),
      exclude_spaces: listToCsv(cfg.exclude_spaces),
      track: cfg.track !== undefined ? String(cfg.track) : '',
      user_id: cfg.user_id !== undefined ? String(cfg.user_id) : '',
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source?.id],
  )

  const { register, handleSubmit, setError, formState } = useForm<FormValues>({
    defaultValues: defaults as Partial<FormValues>,
  })

  // Step 1: adapter picker (skipped entirely in edit mode).
  if (!picked) {
    return (
      <div className="space-y-3">
        <p className="font-medium">Pick an adapter type</p>
        {adapterTypes.isPending && (
          <p className="text-sm text-muted-foreground">Loading adapter types…</p>
        )}
        <div className="flex flex-wrap gap-2">
          {(adapterTypes.data ?? []).map((t) => {
            const noConn =
              t.requires_connection && (connections.data ?? []).length === 0
            return (
              <div key={t.adapter_type} className="flex flex-col">
                <Button
                  disabled={noConn}
                  onClick={() => setPicked(t.adapter_type)}
                >
                  {t.adapter_type}
                </Button>
                {noConn && (
                  <span className="mt-1 max-w-[12rem] text-xs text-muted-foreground">
                    Needs a connection — none configured (add one in config.yml).
                  </span>
                )}
              </div>
            )
          })}
        </div>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    )
  }

  const buildConfig = (values: FormValues): Record<string, unknown> => {
    const config: Record<string, unknown> = {}
    if (picked === 'github') {
      config.repos = toList((values as { repos?: string }).repos)
    } else if (picked === 'email') {
      const v = values as { label_filters?: string; max_results?: string }
      if (v.label_filters) config.label_filters = toList(v.label_filters)
      if (v.max_results) config.max_results = Number(v.max_results)
    } else if (picked === 'calendar') {
      const v = values as { calendar_ids?: string; lookahead_hours?: string }
      if (v.calendar_ids) config.calendar_ids = toList(v.calendar_ids)
      if (v.lookahead_hours) config.lookahead_hours = Number(v.lookahead_hours)
    } else if (picked === 'chat') {
      const v = values as {
        spaces?: string
        exclude_spaces?: string
        track?: string
        user_id?: string
      }
      if (v.spaces) config.spaces = toList(v.spaces)
      if (v.exclude_spaces) config.exclude_spaces = toList(v.exclude_spaces)
      if (v.track) config.track = v.track
      if (v.user_id) config.user_id = v.user_id
    }
    return config
  }

  const onSubmit = handleSubmit(async (values) => {
    const config = buildConfig(values)
    const connection = GOOGLE_ADAPTERS.has(picked)
      ? (values as { connection?: string }).connection
      : undefined
    try {
      if (editing) {
        await edit.mutateAsync({ id: source!.id, body: { config, schedule } })
        toast.success('Source updated')
      } else {
        await create.mutateAsync({
          adapter_type: picked,
          config,
          schedule,
          enabled: true,
          connection,
        })
        toast.success('Source added')
      }
      onDone()
    } catch (e) {
      const err = e as ApiError
      // Map server 422 field errors (config_errors) onto the offending fields.
      try {
        const parsed = JSON.parse(err.message) as {
          config_errors?: { loc: (string | number)[]; msg: string }[]
        }
        const fieldErrors = parsed.config_errors ?? []
        if (fieldErrors.length === 0) throw new Error('no field errors')
        for (const fe of fieldErrors) {
          const field = String(fe.loc[fe.loc.length - 1]) as keyof FormValues
          setError(field, { message: fe.msg })
        }
      } catch {
        toast.error(`${editing ? 'Update' : 'Create'} failed: ${err.message}`)
      }
    }
  })

  const pending = editing ? edit.isPending : create.isPending
  const conns: Connection[] = connections.data ?? []

  const listField = (label: string, name: keyof FormValues, hint?: string) => (
    <label className="block text-sm">
      {label}
      <input aria-label={label} {...register(name)} className={inputCls} />
      {hint && (
        <span className="block text-xs text-muted-foreground">{hint}</span>
      )}
    </label>
  )

  return (
    <form onSubmit={onSubmit} className="max-w-md space-y-3">
      <p className="text-sm text-muted-foreground">
        adapter_type: {picked} (immutable)
      </p>

      {GOOGLE_ADAPTERS.has(picked) && (
        <label className="block text-sm">
          connection
          <select
            aria-label="connection"
            {...register('connection' as keyof FormValues)}
            className={inputCls}
          >
            <option value="">Select a connection…</option>
            {conns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
                {c.healthy ? '' : ' (unhealthy)'}
              </option>
            ))}
          </select>
          {'connection' in formState.errors && formState.errors.connection && (
            <span className="text-xs text-destructive">
              {formState.errors.connection.message as string}
            </span>
          )}
          <span className="block text-xs text-muted-foreground">
            Authenticates via the selected connection — no secret needed.
          </span>
        </label>
      )}

      {picked === 'github' && (
        <label className="block text-sm">
          repos (comma-separated)
          <input aria-label="repos" {...register('repos')} className={inputCls} />
          {'repos' in formState.errors && formState.errors.repos && (
            <span className="text-xs text-destructive">
              {formState.errors.repos.message as string}
            </span>
          )}
          <span className="block text-xs text-muted-foreground">
            Uses ambient gh auth — no secret needed.
          </span>
        </label>
      )}

      {picked === 'email' && (
        <>
          {listField('label_filters (comma-separated)', 'label_filters' as keyof FormValues)}
          {listField('max_results', 'max_results' as keyof FormValues)}
        </>
      )}

      {picked === 'calendar' && (
        <>
          {listField('calendar_ids (comma-separated)', 'calendar_ids' as keyof FormValues)}
          {listField('lookahead_hours', 'lookahead_hours' as keyof FormValues)}
        </>
      )}

      {picked === 'chat' && (
        <>
          {listField('spaces (comma-separated)', 'spaces' as keyof FormValues)}
          {listField('exclude_spaces (comma-separated)', 'exclude_spaces' as keyof FormValues)}
          {listField('track (all | participating | mentioned)', 'track' as keyof FormValues)}
          {listField('user_id', 'user_id' as keyof FormValues)}
        </>
      )}

      <div className="space-y-2">
        <label className="block text-sm">
          Schedule preset
          <select
            aria-label="Schedule preset"
            value={CRON_PRESETS.some((p) => p.cron === schedule) ? schedule : ''}
            disabled={advanced}
            onChange={(e) => setSchedule(e.target.value)}
            className={inputCls}
          >
            {CRON_PRESETS.map((p) => (
              <option key={p.cron} value={p.cron}>
                {p.label}
              </option>
            ))}
            {(advanced || !CRON_PRESETS.some((p) => p.cron === schedule)) && (
              <option value="">Custom</option>
            )}
          </select>
        </label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setAdvanced((a) => !a)}
        >
          {advanced ? 'Use presets' : 'Advanced'}
        </Button>
        {advanced && (
          <label className="block text-sm">
            Custom cron
            <input
              aria-label="Custom cron"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className={`${inputCls} font-mono`}
            />
          </label>
        )}
        <p className="text-xs text-muted-foreground">{nextRunPreview(schedule)}</p>
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {editing ? 'Save changes' : 'Create source'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
