import { act, render, renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { clearHeldAttempts } from '../../lib/heldAttempts'
import { AttemptFields, AttemptLock, keepsAttemptKey, useAttemptKey, type AttemptCheck } from './attempt'

const problem = (status: number, code = 'x') => new ApiError({ status, code, title: 't', type: 'about:blank' } as never)
const outcome = (settled: boolean, ...statuses: string[]) => ({ settled, statuses, amount_minor: 500 })

describe('keepsAttemptKey', () => {
  it('keeps the key when the outcome is unknown or the key was already used for other values', () => {
    expect(keepsAttemptKey(new TypeError('Failed to fetch'))).toBe(true)
    expect(keepsAttemptKey(problem(503, 'provider-unavailable'))).toBe(true)
    expect(keepsAttemptKey(problem(500, 'internal-error'))).toBe(true)
    expect(keepsAttemptKey(problem(409, 'request-in-progress'))).toBe(true)
    expect(keepsAttemptKey(problem(409, 'idempotency-key-reused'))).toBe(true) // S3: never a fresh key on its own
  })
  it('ends the attempt after a success or a definite refusal', () => {
    expect(keepsAttemptKey(null)).toBe(false)
    expect(keepsAttemptKey(problem(402, 'payment-declined'))).toBe(false)
    expect(keepsAttemptKey(problem(422, 'validation-failed'))).toBe(false)
  })
})

describe('useAttemptKey', () => {
  it('locks the key after an unknown outcome until a final answer for that key', () => {
    const { result } = renderHook(() => useAttemptKey())
    const first = result.current.key
    act(() => result.current.settle(problem(422)))
    expect(result.current.key).not.toBe(first) // a refusal of a new attempt: nothing happened
    const second = result.current.key
    act(() => result.current.settle(problem(503)))
    expect([result.current.key, result.current.locked]).toEqual([second, true])
    act(() => result.current.restart())
    act(() => result.current.settle(problem(422))) // not an answer about the first attempt
    act(() => result.current.settle(problem(409, 'idempotency-key-reused')))
    expect([result.current.key, result.current.locked]).toEqual([second, true])
    act(() => result.current.settle(null))
    expect(result.current.locked).toBe(false)
    expect(result.current.key).not.toBe(second)
    act(() => result.current.settle(new TypeError('Failed to fetch')))
    act(() => result.current.settle(problem(402, 'payment-declined'))) // a decline is final
    expect(result.current.locked).toBe(false)
  })

  it('keeps the lock across a remount of the same form', () => {
    const scope = `form-${Math.random()}`
    const first = renderHook(() => useAttemptKey(scope))
    act(() => first.result.current.settle(problem(500)))
    const key = first.result.current.key
    first.unmount()
    const again = renderHook(() => useAttemptKey(scope))
    expect([again.result.current.key, again.result.current.locked]).toEqual([key, true])
    act(() => again.result.current.settle(null))
    again.unmount()
    expect(renderHook(() => useAttemptKey(scope)).result.current.locked).toBe(false)
  })

  it('frees a locked form on a definite decline whatever its status, and keeps the values with the key', () => {
    const scope = `form-${Math.random()}`
    const first = renderHook(() => useAttemptKey<{ amount: string }>(scope))
    act(() => first.result.current.settle(problem(503), { amount: '12.00' }))
    first.unmount()
    const again = renderHook(() => useAttemptKey<{ amount: string }>(scope))
    expect([again.result.current.locked, again.result.current.saved]).toEqual([true, { amount: '12.00' }])
    act(() => again.result.current.settle(problem(409, 'payment-failed'))) // portal, guest and mobile declines
    expect(again.result.current.locked).toBe(false)
    again.unmount()
    expect(renderHook(() => useAttemptKey(scope)).result.current.saved).toBeUndefined()
  })

  it('never hands a held attempt to another signed-in person, and forgets the request once it settles', () => {
    const scope = `desk-${Math.random()}`
    clearHeldAttempts('staff-a')
    const mine = renderHook(() => useAttemptKey<{ token: string }>(scope))
    act(() => mine.result.current.settle(problem(503), { token: 'tok_card_ok' }))
    mine.unmount()
    clearHeldAttempts('staff-b') // the next person signs in at the same browser
    const theirs = renderHook(() => useAttemptKey<{ token: string }>(scope))
    expect([theirs.result.current.locked, theirs.result.current.saved]).toEqual([false, undefined])
    act(() => theirs.result.current.settle(problem(503), { token: 'tok_card_ok' }))
    act(() => theirs.result.current.settle(null)) // settled: the held request and its token are dropped
    theirs.unmount()
    expect(renderHook(() => useAttemptKey(scope)).result.current.saved).toBeUndefined()
    clearHeldAttempts()
  })

  it('drops a late answer from a form that belonged to whoever was signed in before', () => {
    const scope = `late-${Math.random()}`
    clearHeldAttempts('staff-a')
    const mine = renderHook(() => useAttemptKey<{ amount: string }>(scope))
    clearHeldAttempts('staff-b') // B signs in while A's request is still out
    act(() => mine.result.current.settle(problem(503), { amount: '9.00' }))
    mine.unmount()
    expect(renderHook(() => useAttemptKey(scope)).result.current.locked).toBe(false) // nothing written into B's slot
    clearHeldAttempts()
  })

  it('frees the form only when the server says no money moved', async () => {
    const answers = [() => outcome(false, 'initiated'), () => { throw problem(404, 'not-found') }, () => outcome(true, 'succeeded'), () => outcome(true, 'failed')]
    const check: AttemptCheck = vi.fn(async () => {
      const next = answers.shift()
      if (!next) throw new Error('no answer left')
      return next()
    })
    const { result } = renderHook(() => useAttemptKey(undefined, check))
    act(() => result.current.settle(problem(503)))
    const key = result.current.key
    for (const note of [/still being confirmed/, /Nothing was recorded/, /went through. Try again/]) {
      await act(() => result.current.verify?.())
      expect([result.current.key, result.current.locked]).toEqual([key, true])
      expect(result.current.note).toMatch(note)
    }
    await act(() => result.current.verify?.())
    expect(result.current.locked).toBe(false)
    expect(result.current.key).not.toBe(key)
    expect(result.current.note).toMatch(/was declined. You can change the form now/)
    expect(check).toHaveBeenCalledWith(key)
  })
})

describe('AttemptLock and AttemptFields', () => {
  it('disable the inputs and offer only the check while locked', async () => {
    const check: AttemptCheck = vi.fn(async () => outcome(true, 'cancelled'))
    function Form() {
      const attempt = useAttemptKey(undefined, check)
      return (
        <>
          <AttemptLock attempt={attempt} />
          <AttemptFields attempt={attempt}>
            <input aria-label="Amount" />
          </AttemptFields>
          <button onClick={() => attempt.settle(problem(503))}>Fail</button>
        </>
      )
    }
    render(<Form />)
    expect(screen.getByLabelText('Amount')).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Fail' }))
    expect(screen.getByLabelText('Amount')).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('nothing will be charged twice')
    await userEvent.click(screen.getByRole('button', { name: 'Check what happened' }))
    expect(screen.getByLabelText('Amount')).toBeEnabled()
    expect(screen.getByRole('status')).toHaveTextContent('was cancelled')
  })
})
