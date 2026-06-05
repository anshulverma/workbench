// ui/src/api.ts

let _token: string | null = null

/**
 * Fetch the API token from the server on first call.
 * The /api/auth/token endpoint is behind auth middleware,
 * so in production the initial page load sets a session cookie
 * or the token is passed via query param on first load.
 * In dev mode, the Vite proxy handles forwarding.
 */
async function getToken(): Promise<string> {
  if (_token) return _token
  try {
    const res = await fetch('/api/auth/token')
    if (res.ok) {
      const data = await res.json()
      _token = data.token
      return _token!
    }
  } catch {
    // fallback: token not available
  }
  return ''
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchActions(
  params?: Record<string, string>,
): Promise<{ categories: Record<string, Action[]>; total: number }> {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  const headers = await authHeaders()
  const res = await fetch(`/api/actions${query}`, { headers })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  return res.json()
}

export async function markDone(id: string): Promise<void> {
  const headers = await authHeaders()
  await fetch(`/api/actions/${id}/done`, {
    method: 'POST',
    headers,
  })
}

export async function changePriority(
  id: string,
  priority: string,
): Promise<void> {
  const headers = {
    ...(await authHeaders()),
    'Content-Type': 'application/json',
  }
  await fetch(`/api/actions/${id}/priority`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ priority }),
  })
}

export async function snooze(id: string, hours: number): Promise<void> {
  const headers = {
    ...(await authHeaders()),
    'Content-Type': 'application/json',
  }
  await fetch(`/api/actions/${id}/snooze`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ hours }),
  })
}

export interface Action {
  id: string
  summary: string
  priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string
  action_category: string | null
  created_at: string
}
