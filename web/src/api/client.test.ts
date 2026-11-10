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

  it('refreshes once on 401 and retries with the same idempotency key and the new CSRF token', async () => {
    let attempts = 0
    const calls = mockFetch({
      'POST /api/v1/staff-users/u1/deactivate': () => (++attempts === 1 ? { status: 401, body: { code: 'unauthenticated' } } : { status: 200, body: { id: 'u1' } }),
      'POST /api/v1/auth/refresh': { status: 200, body: { csrf_token: 'csrf-2' } },
    })
    setCsrfToken('csrf-1')
    await api.post('/api/v1/staff-users/{staff_user_id}/deactivate', { path: { staff_user_id: 'u1' } })
    const [first, refresh, retry] = calls
    expect(refresh?.url).toBe('/api/v1/auth/refresh')
    expect(retry?.headers['idempotency-key']).toBe(first?.headers['idempotency-key'])
    expect(retry?.headers['x-csrf-token']).toBe('csrf-2')
  })

  it('reports the session as gone when the refresh fails', async () => {
    mockFetch({
      'GET /api/v1/tenant': { status: 401, body: { code: 'unauthenticated' } },
      'POST /api/v1/auth/refresh': { status: 401, body: { code: 'session-revoked' } },
    })
    const gone = vi.fn()
    setUnauthenticatedHandler(gone)
    await expect(api.get('/api/v1/tenant')).rejects.toBeInstanceOf(ApiError)
    expect(gone).toHaveBeenCalledOnce()
  })
})
