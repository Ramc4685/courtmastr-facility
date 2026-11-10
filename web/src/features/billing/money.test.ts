import { describe, expect, it } from 'vitest'
import { formatMoney, parseMoney, toMoneyInput } from './money'

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
