import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { keepsAttemptKey } from './shared'

const problem = (status: number, code = 'x') => new ApiError({ status, code, title: 't', type: 'about:blank' } as never)

describe('keepsAttemptKey', () => {
  it('keeps the key when the outcome is unknown, so a retry replays the same charge', () => {
    expect(keepsAttemptKey(new TypeError('Failed to fetch'))).toBe(true)
    expect(keepsAttemptKey(problem(503, 'provider-unavailable'))).toBe(true)
    expect(keepsAttemptKey(problem(500, 'internal-error'))).toBe(true)
    expect(keepsAttemptKey(problem(409, 'request-in-progress'))).toBe(true)
  })
  it('mints a new key after a success or a definite refusal', () => {
    expect(keepsAttemptKey(null)).toBe(false)
    expect(keepsAttemptKey(problem(402, 'payment-declined'))).toBe(false)
    expect(keepsAttemptKey(problem(422, 'validation-failed'))).toBe(false)
    expect(keepsAttemptKey(problem(409, 'idempotency-key-reused'))).toBe(false)
  })
})
