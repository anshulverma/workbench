// Settings → System sub-tab (extracted from Settings.tsx for the sub-tab
// refactor, Slice 8).
//
// Renders App Version, Config Version, Subsystem Health badges, redacted
// config sections, locked Secrets Vault, and Download Backup. All read-only;
// no writes. The parent Settings tab container owns the h1 + tab bar.

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

export function SettingsSystem() {
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
      <div className="flex items-center justify-end">
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
          zep_memory connection degraded — showing last-known component statuses
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
        <h2 className="mb-2 font-semibold">Subsystem Health</h2>
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
          Config Secrets Vault
        </h2>
        <p className="text-sm text-muted-foreground">
          Locked — secrets are redacted server-side and never exposed to the dashboard.
        </p>
      </section>
    </div>
  )
}
