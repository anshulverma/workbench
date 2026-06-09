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
import { Mono } from '@/components/Mono'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
    <form onSubmit={onSubmit} className="max-w-md space-y-4">
      <label className="block space-y-1.5 text-body-sm">
        <span className="font-medium text-muted-foreground">space_id</span>
        <Input
          aria-label="space_id"
          mono
          {...register('space_id')}
        />
        {formState.errors.space_id && (
          <span className="block text-xs text-destructive">
            {formState.errors.space_id.message}
          </span>
        )}
      </label>
      <label className="block space-y-1.5 text-body-sm">
        <span className="font-medium text-muted-foreground">timeout_seconds</span>
        <Input
          aria-label="timeout_seconds"
          inputMode="numeric"
          mono
          {...register('timeout_seconds')}
        />
        {formState.errors.timeout_seconds && (
          <span className="block text-xs text-destructive">
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
        <Card
          role="status"
          className="border-primary/40 bg-primary/5"
        >
          <CardHeader className="flex-row items-center gap-2 space-y-0 pb-2">
            <HealthBadge status="not-configured" />
            <CardTitle className="text-title-md">No messenger configured</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-body-sm text-muted-foreground">
            <p>
              Triage cards are queued but unsent. Pending triage cards:{' '}
              <Mono className="font-semibold text-foreground">{count}</Mono>
            </p>
            <p>
              Configure a messenger in config.yml to start delivering triage
              cards.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Empty: configured but no allowlisted config to show (e.g. console messenger).
  const hasConfig =
    data.config.space_id !== undefined || data.config.timeout_seconds !== undefined

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Messenger</h1>

      <Card>
        <CardHeader divided className="flex-row items-center gap-2 space-y-0">
          <CardTitle className="text-title-md">
            {data.class ?? data.type}
          </CardTitle>
          <HealthBadge status={reachabilityStatus(data.reachable)} />
          <span className="text-mono-label font-mono text-muted-foreground">
            {reachabilityLabel(data.reachable)}
          </span>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-body-sm">
            <dt className="text-muted-foreground">type</dt>
            <dd>
              <Mono>{data.type}</Mono>
            </dd>
            {data.config.space_id !== undefined && (
              <>
                <dt className="text-muted-foreground">space_id</dt>
                <dd>
                  <Mono>{data.config.space_id}</Mono>
                </dd>
              </>
            )}
            {data.config.timeout_seconds !== undefined && (
              <>
                <dt className="text-muted-foreground">timeout_seconds</dt>
                <dd>
                  <Mono>{data.config.timeout_seconds}</Mono>
                </dd>
              </>
            )}
          </dl>
          {data.checked_at && (
            <p className="text-mono-label font-mono text-muted-foreground">
              Reachability checked at{' '}
              {new Date(data.checked_at).toLocaleString()}
            </p>
          )}
        </CardContent>
      </Card>

      {hasConfig ? (
        <Card>
          <CardHeader divided>
            <CardTitle className="text-title-md">Edit configuration</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <EditConfigForm data={data} />
          </CardContent>
        </Card>
      ) : (
        <EmptyState message="This messenger has no editable configuration." />
      )}
    </div>
  )
}
