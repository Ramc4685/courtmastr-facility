/** Portal theming from the tenant's brand colours (SSP-14). A colour is used only where it keeps WCAG 2.1 AA in
 * light mode: primary carries white text and is text on white (4.5:1); accent is the focus ring on the page (3:1).
 * Otherwise, and always in dark mode, the product defaults stay. */

const WHITE = '#ffffff'

function channels(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)?.[1]
  if (!m) return null
  const n = parseInt(m, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

export function contrastRatio(a: string, b: string): number {
  const ca = channels(a)
  const cb = channels(b)
  if (!ca || !cb) return 1
  const [la, lb] = [luminance(ca), luminance(cb)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

const rgb = (hex: string) => (channels(hex) ?? [0, 0, 0]).join(' ')
const darker = (hex: string) => (channels(hex) ?? [0, 0, 0]).map((c) => Math.round(c * 0.82)).join(' ')

/** The CSS custom properties to set, or null for each colour that falls back. */
export function brandVars(primary?: string | null, accent?: string | null): Record<string, string> {
  const vars: Record<string, string> = {}
  if (primary && contrastRatio(primary, WHITE) >= 4.5) {
    vars['--primary'] = rgb(primary)
    vars['--primary-hover'] = darker(primary)
    vars['--on-primary'] = '255 255 255'
  }
  if (accent && contrastRatio(accent, WHITE) >= 3) vars['--accent'] = rgb(accent)
  return vars
}

/** A stylesheet scoping the vars to `.tenant-theme`, switched off in dark mode (explicit or from the system). */
export function brandStyleSheet(primary?: string | null, accent?: string | null): string {
  const vars = Object.entries(brandVars(primary, accent))
  if (!vars.length) return ''
  const on = vars.map(([k, v]) => `${k}: ${v};`).join(' ')
  const off = vars.map(([k]) => `${k}: inherit;`).join(' ')
  return `:root:not([data-theme='dark']) .tenant-theme { ${on} }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .tenant-theme { ${off} } }`
}
