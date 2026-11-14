import { describe, expect, it } from 'vitest'
import { formatMoney, parseMoney, refundOutcome, toMoneyInput } from './money'

describe('money helpers', () => {
  it('parses typed amounts to minor units without floating point', () => {
    expect(parseMoney('12')).toBe(1200)
    expect(parseMoney('12.5')).toBe(1250)
    expect(parseMoney('0.07')).toBe(7)
    expect(parseMoney('1,234.56')).toBe(123456)
    expect(parseMoney('$ 19.99')).toBe(1999)
    expect(parseMoney('-3.10')).toBe(-310)
    expect(parseMoney('1.005')).toBeNull() // no sub-cent amounts
    expect(parseMoney('abc')).toBeNull()
    expect(parseMoney('')).toBeNull()
  })

  it('round-trips through the editable form', () => {
    for (const minor of [0, 1, 99, 1250, 123456]) expect(parseMoney(toMoneyInput(minor))).toBe(minor)
  })

  it('formats minor units in the tenant currency', () => {
    expect(formatMoney(123456, 'USD')).toMatch(/1,234\.56/)
  })
})

describe('refundOutcome', () => {
  it('announces success only when every leg was refunded', () => {
    expect(refundOutcome([{ amount_minor: 500, status: 'succeeded' }])).toEqual({ tone: 'success', message: `Refunded ${formatMoney(500)}.` })
  })

  it('names a declined leg and its reason, and what was refunded', () => {
    const outcome = refundOutcome([
      { amount_minor: 500, status: 'succeeded' },
      { amount_minor: 500, status: 'failed', failure_message: 'Declined by the bank.' },
    ])
    expect(outcome.tone).toBe('error')
    expect(outcome.message).toBe(`Refunded ${formatMoney(500)}. ${formatMoney(500)} was not refunded (Declined by the bank.); it stays as account credit.`)
  })

  it('says a pending leg is still with the processor', () => {
    const outcome = refundOutcome([{ amount_minor: 300, status: 'pending' }])
    expect(outcome).toEqual({ tone: 'success', message: `Refunded ${formatMoney(0)}. ${formatMoney(300)} is with the processor and settles shortly.` })
  })

  it('treats a declined card refund as not refunded', () => {
    expect(refundOutcome([{ amount_minor: 600, status: 'failed', failure_message: null }]).tone).toBe('error')
  })
})
