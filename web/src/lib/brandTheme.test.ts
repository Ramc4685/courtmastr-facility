import { describe, expect, it } from 'vitest'
import { brandStyleSheet, brandVars, contrastRatio } from './brandTheme'

describe('brand theme', () => {
  it('measures contrast the WCAG way', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
    expect(contrastRatio('#ffffff', '#ffffff')).toBe(1)
  })

  it('keeps a colour that passes AA and drops one that fails', () => {
    expect(brandVars('#1a4d8f', '#f2a900')).toMatchObject({ '--primary': '26 77 143', '--on-primary': '255 255 255' })
    expect(brandVars('#ffeb3b', null)).toEqual({}) // yellow under white text fails 4.5:1
    expect(brandVars(null, '#fff59d')).toEqual({}) // a pale focus ring fails 3:1
  })

  it('scopes the vars to the portal and turns them off in dark mode', () => {
    expect(brandStyleSheet(null, null)).toBe('')
    const css = brandStyleSheet('#1a4d8f', null)
    expect(css).toContain(".tenant-theme { --primary: 26 77 143;")
    expect(css).toContain('prefers-color-scheme: dark')
  })
})
