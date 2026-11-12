import { describe, expect, it } from 'vitest'
import { CODE128_PATTERNS, code128 } from './code128'

describe('code128', () => {
  it('has 107 distinct patterns of 11 modules and a 13-module stop', () => {
    const sum = (p: string) => p.split('').reduce((s, d) => s + Number(d), 0)
    expect(CODE128_PATTERNS).toHaveLength(107)
    expect(new Set(CODE128_PATTERNS).size).toBe(107)
    expect(CODE128_PATTERNS.slice(0, 106).every((p) => p.length === 6 && sum(p) === 11)).toBe(true)
    expect(sum(CODE128_PATTERNS[106] ?? '')).toBe(13)
  })

  it('encodes start B, the data, the mod-103 check and the stop', () => {
    const bars = code128('AB1') ?? []
    // start + 3 characters + check, 6 widths each, then the 7-width stop
    expect(bars).toHaveLength(5 * 6 + 7)
    expect(bars.slice(0, 6).join('')).toBe('211214')
    // check = (104 + 33*1 + 34*2 + 17*3) % 103 = 50
    expect(bars.slice(24, 30).join('')).toBe(CODE128_PATTERNS[50])
    expect(bars.slice(30).join('')).toBe('2331112')
  })

  it('refuses text it cannot encode', () => {
    expect(code128('')).toBeNull()
    expect(code128('café')).toBeNull()
  })
})
