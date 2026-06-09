// Settings page (spec Design Section 2.8 / §12) — read-only system info, no
// writes.
//
// Renders App Version (`health.version`) + Config Version (`config.version`,
// "—" fallback), the Subsystem Health badges (storage + connections), and the
// redacted pipeline/scheduler/retention/alerting config sections from GET
// /api/debug/config (secret-redacted server-side, ADR0017) through the pure
// <JsonHighlight> tokenizer (no dangerouslySetInnerHTML). A locked
// CONFIG_SECRETS_VAULT panel makes the no-secrets posture explicit (values are
// never fetched/rendered). DOWNLOAD BACKUP performs a client-side Blob download
// of the already-redacted config. The vanity Runtime Metadata block
// (kernel/arch/memory/network-latency) is dropped — there is no real data
// source and we never fabricate.
//
// A 503 from /health (storage down) drives the degraded banner; a config-fetch
// failure drives the error state with the X-Request-ID.

import { Download, Lock } from 'lucide-react'
import { useHealth, useDebugConfig } from '@/hooks/useSettings'
import { HealthBadge } from '@/components/HealthBadge'
import { JsonHighlight } from '@/components/JsonHighlight'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

const SECTIONS = ['pipeline', 'scheduler', 'retention', 'alerting']

function badgeStatus(status: string | undefined): string {
  return status === 'healthy' ? 'healthy' : 'erroring'
}

// Client-side download of the already-redacted config as a JSON file. Uses an
// anchor + URL.createObjectURL (no server round-trip, no secret exposure).
function downloadBackup(config: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(config, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'workbench-config.json'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function Settings() {
  const health = useHealth()
  const cfg = useDebugConfig()

  if (health.isPending || cfg.isPending) {
    return (
      <div data-testid="settings-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  // Unauthorized: the token endpoint 401d (surfaced on whichever query ran).
  const healthErr = health.error as ApiError | null
  const cfgErr = cfg.error as ApiError | null
  if (
    (health.isError && healthErr?.status === 401) ||
    (cfg.isError && cfgErr?.status === 401)
  ) {
    return (
      <div role="alert" className="p-6">
        token unavailable; check tunnel/binding
      </div>
    )
  }

  // Config fetch failure (non-503, non-auth) is the error state.
  if (cfg.isError) {
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load config: {cfgErr?.message}
        {cfgErr?.requestId && (
          <div className="text-xs">Request ID: {cfgErr.requestId}</div>
        )}
      </div>
    )
  }

  // /health returns 503 (storage down) -> ApiError; otherwise the body carries
  // status. Treat both as degraded so the banner + last-known statuses show.
  const degraded =
    (health.isError && healthErr?.status === 503) ||
    health.data?.status === 'unhealthy'

  const config = (cfg.data?.config ?? {}) as Record<
    string,
    Record<string, unknown>
  >
  const components = health.data?.components
  const connections = components?.connections ?? {}

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Settings</h1>
        <Button
          variant="outline"
          size="sm"
          onClick={() => downloadBackup(config)}
        >
          <Download aria-hidden="true" />
          Download Backup
        </Button>
      </div>

      {degraded && (
        <div
          role="alert"
          className="rounded border border-destructive p-3 text-sm text-destructive"
        >
          storage down — showing last-known component statuses
        </div>
      )}

      <section className="rounded border border-border p-3">
        <h2 className="mb-2 font-semibold">Versions</h2>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span>App version: {health.data?.version ?? '—'}</span>
          <span>Config version: {String(config.version ?? '—')}</span>
        </div>
      </section>

      <section className="rounded border border-border p-3">
        <h2 className="mb-2 font-semibold">Component health</h2>
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-32">storage</span>
            <HealthBadge status={badgeStatus(components?.storage.status)} />
          </div>
          {Object.entries(connections).map(([name, c]) => (
            <div key={name} className="flex items-center gap-2">
              <span className="w-32">{name}</span>
              <HealthBadge status={badgeStatus(c.status)} />
            </div>
          ))}
          {Object.keys(connections).length === 0 && (
            <div className="text-xs text-muted-foreground">
              No connections configured.
            </div>
          )}
        </div>
      </section>

      {SECTIONS.map((s) => (
        <section key={s} className="rounded border border-border p-3">
          <h2 className="mb-2 font-semibold">{s}</h2>
          <JsonHighlight json={JSON.stringify(config[s] ?? {}, null, 2)} />
        </section>
      ))}

      {/* Secrets vault: a locked placeholder. Secret values are NEVER fetched
          or rendered (ADR0017); the redaction is server-side. */}
      <section
        data-testid="secrets-vault"
        className="rounded border border-border p-3"
      >
        <h2 className="mb-2 flex items-center gap-2 font-semibold">
          <Lock aria-hidden="true" className="size-4 text-muted-foreground" />
          Secrets Vault
        </h2>
        <p className="text-sm text-muted-foreground">
          Locked — secrets are not exposed to the dashboard.
        </p>
      </section>
    </div>
  )
}
