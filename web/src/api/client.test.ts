import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/fetchMock'
import { api, ApiError, fieldErrors, setCsrfToken, setUnauthenticatedHandler } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

describe('api client', () => {
  it('sends the CSRF token and an idempotency key on mutations, not on reads', async () => {
    const calls = mockFetch({
      'GET /api/v1/tenant': { status: 200, body: { id: 't' } },
      'POST /api/v1/locations': { status: 201, body: { id: 'l' } },
    })
    setCsrfToken('csrf-1')
    await api.get('/api/v1/tenant')
    await api.post('/api/v1/locations', { body: { name: 'A', time_zone: 'UTC', country_code: 'US' } })
    expect(calls[0]?.headers['x-csrf-token']).toBeUndefined()
    expect(calls[0]?.headers['idempotency-key']).toBeUndefined()
    expect(calls[1]?.headers['x-csrf-token']).toBe('csrf-1')
    expect(calls[1]?.headers['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/)
    expect(calls[1]?.headers['content-type']).toBe('application/json')
  })

  it('uses a caller-supplied idempotency key so one user action can be retried safely', async () => {
    const calls = mockFetch({ 'POST /api/v1/locations': { status: 201, body: { id: 'l' } } })
    const body = { name: 'A', time_zone: 'UTC', country_code: 'US' }
    await api.post('/api/v1/locations', { body, idempotencyKey: 'k-1' })
    await api.post('/api/v1/locations', { body, idempotencyKey: 'k-1' })
    expect(calls.map((c) => c.headers['idempotency-key'])).toEqual(['k-1', 'k-1'])
  })

  it('returns the body of a 202 and undefined for an empty one', async () => {
    mockFetch({
      'POST /api/v1/bookings': { status: 202, body: { status_url: '/api/v1/booking-series/s/runs/r' } },
      'POST /api/v1/auth/magic-links': { status: 202 },
    })
    const created = await api.post('/api/v1/bookings', { body: { location_id: 'l', kind: 'block', starts_at: 'a', ends_at: 'b', resources: [{ resource_id: 'r' }], include_linked_resources: true, on_conflict: 'abort', override_policy: false } })
    expect(created?.status_url).toBe('/api/v1/booking-series/s/runs/r')
    expect(await api.post('/api/v1/auth/magic-links', { body: { email: 'a@example.com', audience: 'staff' } })).toBeUndefined()
  })

  it('turns problem+json into ApiError with field errors by pointer', async () => {
    mockFetch({
      'POST /api/v1/locations': {
        status: 422,
        body: { code: 'validation-failed', detail: 'The request is not valid.', errors: [{ pointer: '/name', code: 'missing', detail: 'Field required' }] },
      },
    })
    const error = await api.post('/api/v1/locations', { body: { name: '', time_zone: 'UTC', country_code: 'US' } }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).code).toBe('validation-failed')
    expect(fieldErrors(error)).toEqual({ name: 'Field required' })
  })

  it('ends the session on a 401: web sessions have no refresh token to trade', async () => {
    const calls = mockFetch({ 'GET /api/v1/tenant': { status: 401, body: { code: 'unauthenticated' } } })
    const gone = vi.fn()
    setUnauthenticatedHandler(gone)
    await expect(api.get('/api/v1/tenant')).rejects.toBeInstanceOf(ApiError)
    expect(gone).toHaveBeenCalledOnce()
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/tenant'])
  })

  it('sends the pre-session token, not the session one, on sign-in (login CSRF)', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre-1' } },
      'POST /api/v1/auth/sign-in': { status: 401, body: { code: 'invalid-credentials' } },
    })
    const gone = vi.fn()
    setUnauthenticatedHandler(gone)
    setCsrfToken('session-csrf')
    const body = { email: 'a@example.com', password: 'x', audience: 'staff' as const, client_kind: 'web' as const }
    await expect(api.post('/api/v1/auth/sign-in', { body })).rejects.toBeInstanceOf(ApiError)
    expect(calls.find((c) => c.method === 'POST')?.headers['x-csrf-token']).toBe('pre-1')
    expect(gone).not.toHaveBeenCalled() // a 401 from sign-in is an answer, not a lost session
  })

  it('takes a fresh pre-session token once when the old one is refused, keeping the idempotency key', async () => {
    let issued = 0
    let attempts = 0
    const calls = mockFetch({
      'GET /api/v1/auth/pre-session': () => ({ status: 200, body: { csrf_token: `pre-${++issued}` } }),
      'POST /api/v1/auth/magic-links': () => (++attempts === 1 ? { status: 403, body: { code: 'csrf-failed' } } : { status: 202 }),
    })
    await api.post('/api/v1/auth/magic-links', { body: { email: 'a@example.com', audience: 'staff' } })
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts.map((c) => c.headers['x-csrf-token'])).toEqual(['pre-1', 'pre-2'])
    expect(posts[1]?.headers['idempotency-key']).toBe(posts[0]?.headers['idempotency-key'])
  })
})
