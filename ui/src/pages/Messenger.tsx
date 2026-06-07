// Messenger page — view + edit (spec Design Section 2.6).
//
// Read view (GET /api/messenger?check=true): type, class, allowlisted config
// (space_id, timeout_seconds) and a reachability HealthBadge. The secret field
// service_account_key_path is NEVER read from the API nor rendered, and is
// never offered as an input. The edit form (react-hook-form + zod) submits only
// non-secret fields via PATCH /api/messenger (Config Write-Back + hot-swap);
// server 422 field errors map onto the offending fields. When no messenger is
// configured the page degrades to an info state showing the current pending
// triage count (queued but unsent). Implements the five UI states:
// loading / error (with X-Request-ID) / unauthorized / degraded / normal.

import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import {
  useMessenger,
  usePendingCount,
  useUpdateMessenger,
  type MessengerInfo,
} from '@/hooks/useMessenger'
import { HealthBadge } from '@/components/HealthBadge'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'

// Only non-secret, editable fields. timeout_seconds is entered as text and
// coerced to a positive integer; blank leaves it unset.
const formSchema = z.object({
  space_id: z.string().trim().min(1, 'space_id is required'),
  timeout_seconds: z
    .string()
    .trim()
    .optional()
    .refine(
      (v) => !v || (/^\d+$/.test(v) && Number(v) > 0),
      'must be a positive integer',
    ),
})
type FormValues = z.infer<typeof formSchema>

const inputCls = 'mt-1 block w-full rounded border border-border bg-background p-2'

// Map the messenger probe result onto a HealthBadge status. `null`/missing means
// no cheap probe is available (e.g. GoogleChat) — show an unknown badge.
function reachabilityStatus(reachable: boolean | null | undefined): string {
  if (reachable === true) return 'healthy'
  if (reachable === false) return 'erroring'
  return 'never_run'
}

function reachabilityLabel(reachable: boolean | null | undefined): string {
  if (reachable === true) return 'reachable'
  if (reachable === false) return 'unreachable'
  return 'unknown'
}

function EditConfigForm({ data }: { data: MessengerInfo }) {
  const update = useUpdateMessenger()
  const { register, handleSubmit, reset, setError, clearErrors, formState } =
    useForm<FormValues>({
      defaultValues: {
        space_id: data.config.space_id ?? '',
        timeout_seconds:
          data.config.timeout_seconds !== undefined
            ? String(data.config.timeout_seconds)
            : '',
      },
    })

  // Re-sync defaults when the read view refetches the hot-swapped config.
  useEffect(() => {
    reset({
      space_id: data.config.space_id ?? '',
      timeout_seconds:
        data.config.timeout_seconds !== undefined
          ? String(data.config.timeout_seconds)
          : '',
    })
  }, [data.config.space_id, data.config.timeout_seconds, reset])

  const onSubmit = handleSubmit(async (raw) => {
    // Validate non-secret fields with zod (no resolver dep); map issues to fields.
    clearErrors()
    const parsed = formSchema.safeParse(raw)
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const field = issue.path[0]
        if (field === 'space_id' || field === 'timeout_seconds') {
          setError(field, { message: issue.message })
        }
      }
      return
    }
    const values = parsed.data
    const body: { space_id?: string; timeout_seconds?: number } = {
      space_id: values.space_id,
    }
    if (values.timeout_seconds) body.timeout_seconds = Number(values.timeout_seconds)
    try {
      await update.mutateAsync(body)
    } catch (e) {
      const err = e as ApiError
      // Map FastAPI 422 validation errors onto the offending fields when present.
      try {
        const parsed = JSON.parse(err.message) as
          | { loc?: (string | number)[]; msg?: string }[]
          | { detail?: { loc: (string | number)[]; msg: string }[] }
        const list = Array.isArray(parsed) ? parsed : (parsed.detail ?? [])
        let mapped = false
        for (const fe of list) {
          const field = String(fe.loc?.[fe.loc.length - 1] ?? '')
          if (field === 'space_id' || field === 'timeout_seconds') {
            setError(field, { message: fe.msg ?? 'invalid value' })
            mapped = true
          }
        }
        if (!mapped) throw new Error('unmapped')
      } catch {
        /* fallback toast handled by the mutation's onError */
      }
    }
  })

  return (
    <form onSubmit={onSubmit} className="max-w-md space-y-3">
      <label className="block text-sm">
        space_id
        <input aria-label="space_id" {...register('space_id')} className={inputCls} />
        {formState.errors.space_id && (
          <span className="text-xs text-destructive">
            {formState.errors.space_id.message}
          </span>
        )}
      </label>
      <label className="block text-sm">
        timeout_seconds
        <input
          aria-label="timeout_seconds"
          inputMode="numeric"
          {...register('timeout_seconds')}
          className={inputCls}
        />
        {formState.errors.timeout_seconds && (
          <span className="text-xs text-destructive">
            {formState.errors.timeout_seconds.message}
          </span>
        )}
      </label>
      <Button type="submit" disabled={update.isPending}>
        Save
      </Button>
    </form>
  )
}

export function Messenger() {
  const m = useMessenger()
  // Only probe the pending count when there is no messenger to send through.
  const pending = usePendingCount(m.data?.configured === false)

  if (m.isPending) {
    return (
      <div data-testid="messenger-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (m.isError) {
    const err = m.error as ApiError
    if (err.status === 401) {
      return (
        <div role="alert" className="p-6">
          token unavailable; check tunnel/binding
        </div>
      )
    }
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load messenger: {err.message}
        {err.requestId && <div className="text-xs">Request ID: {err.requestId}</div>}
      </div>
    )
  }

  const data = m.data

  // Degraded: no messenger configured. Show what is queued but unsent.
  if (!data.configured) {
    const count = (pending.data ?? []).length
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Messenger</h1>
        <div role="status" className="rounded border border-amber-600/40 bg-amber-600/10 p-4">
          <p className="font-medium">No messenger configured</p>
          <p className="text-sm text-muted-foreground">
            Triage cards are queued but unsent. Pending triage cards:{' '}
            <span className="font-semibold">{count}</span>
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            Configure a messenger in config.yml to start delivering triage cards.
          </p>
        </div>
      </div>
    )
  }

  // Empty: configured but no allowlisted config to show (e.g. console messenger).
  const hasConfig =
    data.config.space_id !== undefined || data.config.timeout_seconds !== undefined

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Messenger</h1>

      <div className="space-y-3 rounded border border-border p-4">
        <div className="flex items-center gap-2">
          <span className="font-medium">{data.class ?? data.type}</span>
          <HealthBadge status={reachabilityStatus(data.reachable)} />
          <span className="text-xs text-muted-foreground">
            {reachabilityLabel(data.reachable)}
          </span>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">type</dt>
          <dd>{data.type}</dd>
          {data.config.space_id !== undefined && (
            <>
              <dt className="text-muted-foreground">space_id</dt>
              <dd className="font-mono">{data.config.space_id}</dd>
            </>
          )}
          {data.config.timeout_seconds !== undefined && (
            <>
              <dt className="text-muted-foreground">timeout_seconds</dt>
              <dd>{data.config.timeout_seconds}</dd>
            </>
          )}
        </dl>
        {data.checked_at && (
          <p className="text-xs text-muted-foreground">
            Reachability checked at {new Date(data.checked_at).toLocaleString()}
          </p>
        )}
      </div>

      {hasConfig ? (
        <div className="space-y-2 rounded border border-border p-4">
          <p className="font-medium">Edit configuration</p>
          <EditConfigForm data={data} />
        </div>
      ) : (
        <EmptyState message="This messenger has no editable configuration." />
      )}
    </div>
  )
}
