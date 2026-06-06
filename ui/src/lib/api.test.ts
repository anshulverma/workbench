// ui/src/lib/api.test.ts
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { apiGet, _resetToken } from './api'

const server = setupServer(
  http.get('/api/auth/token', () => HttpResponse.json({ token: 'tok-123' })),
)

beforeAll(() => server.listen())
afterEach(() => {
  server.resetHandlers()
  _resetToken()
})
afterAll(() => server.close())

describe('api client', () => {
  it('attaches bearer token from the token-vending endpoint', async () => {
    let seen = ''
    server.use(
      http.get('/api/stats/overview', ({ request }) => {
        seen = request.headers.get('Authorization') ?? ''
        return HttpResponse.json({ pending_triage: 0 })
      }),
    )
    const data = await apiGet<{ pending_triage: number }>('/api/stats/overview')
    expect(seen).toBe('Bearer tok-123')
    expect(data.pending_triage).toBe(0)
  })

  it('throws ApiError carrying the X-Request-ID on failure', async () => {
    server.use(
      http.get('/api/stats/overview', () =>
        HttpResponse.json(
          { detail: 'boom' },
          { status: 500, headers: { 'X-Request-ID': 'req-9' } },
        ),
      ),
    )
    await expect(apiGet('/api/stats/overview')).rejects.toMatchObject({
      status: 500,
      requestId: 'req-9',
    })
  })

  it('throws ApiError with status 401 when token endpoint is unauthorized', async () => {
    server.use(
      http.get('/api/auth/token', () => new HttpResponse(null, { status: 401 })),
    )
    await expect(apiGet('/api/stats/overview')).rejects.toMatchObject({
      status: 401,
    })
  })
})
