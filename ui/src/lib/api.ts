// ui/src/lib/api.ts
//
// getToken(): GET /api/auth/token (the Token-Vending Endpoint) returns
// { token }. The endpoint is auth-exempt and same-origin; it is safe only
// under loopback / SSH-tunnel isolation. The token is held in module memory
// for the page session and attached as `Authorization: Bearer ...` to every
// /api call. Errors surface as ApiError carrying the response status and the
// X-Request-ID correlation header.

let _token: string | null = null

export function _resetToken() {
  _token = null
}

export class ApiError extends Error {
  status: number
  requestId: string | null
  constructor(message: string, status: number, requestId: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.requestId = requestId
  }
}

async function getToken(): Promise<string> {
  if (_token) return _token
  const res = await fetch('/api/auth/token')
  if (!res.ok) {
    throw new ApiError('token unavailable', res.status, res.headers.get('X-Request-ID'))
  }
  const data = await res.json()
  _token = data.token
  return _token!
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    ...(await authHeaders()),
    ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  }
  const res = await fetch(path, { ...init, headers })
  const requestId = res.headers.get('X-Request-ID')
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ? JSON.stringify(body.detail) : detail
    } catch {
      /* non-json error body */
    }
    throw new ApiError(detail, res.status, requestId)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const apiGet = <T>(path: string) => request<T>(path)
export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
export const apiPatch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined })
export const apiDelete = <T>(path: string) => request<T>(path, { method: 'DELETE' })

// --- Action Items helpers (used by the legacy ActionList; reused in Phase E) ---

export interface Action {
  id: string
  summary: string
  priority: string
  parent_item: { id: string; summary: string } | null
  action_source: string
  action_category: string | null
  created_at: string
}

export async function fetchActions(
  params?: Record<string, string>,
): Promise<{ categories: Record<string, Action[]>; total: number }> {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  return apiGet(`/api/actions${query}`)
}

export async function markDone(id: string): Promise<void> {
  await apiPost(`/api/actions/${id}/done`)
}

export async function changePriority(id: string, priority: string): Promise<void> {
  await apiPost(`/api/actions/${id}/priority`, { priority })
}

export async function snooze(id: string, hours: number): Promise<void> {
  await apiPost(`/api/actions/${id}/snooze`, { hours })
}
