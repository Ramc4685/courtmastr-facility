import { expect, type Locator, type Page } from '@playwright/test'

// What axe cannot see (docs/status/phase8-o2-accessibility.md): keyboard order and reach, visible focus and its
// contrast, dialog focus handling, target size, reflow and reduced motion. Each check returns problems as text
// so one assertion lists them all.

export const PASSWORD = 'courtside-demo-2026' // dev-only demo password (docs/dev/demo-accounts.md)
export const ADMIN = 'admin@courtside-demo.example.com'
export const MEMBER = 'member@courtside-demo.example.com'

export async function signIn(page: Page, path: string, email = ADMIN) {
  await page.goto(path)
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export async function settled(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('status').filter({ hasText: /^(Loading|Checking)/ })).toHaveCount(0)
}

type Stop = { tag: string; name: string; top: number; left: number; inMain: boolean; inDialog: boolean; ring: boolean; ringContrast: number }

/** The focused element: where it is, whether a focus indicator is drawn, and that indicator's contrast against
 * the background behind it (WCAG 1.4.11, 3:1). */
export function focused(page: Page): Promise<Stop | null> {
  return page.evaluate(async () => {
    // Read after two frames: under reduced motion every property transitions for 0.01ms (index.css), so in the
    // frame of the key press the computed style still holds the pre-focus values (outline: medium currentColor).
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
    const el = document.activeElement as HTMLElement | null
    if (!el || el === document.body) return null
    const parse = (c: string) => (c.match(/[\d.]+/g) ?? []).map(Number)
    const lum = ([r = 0, g = 0, b = 0]: number[]) => {
      const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    }
    const background = () => {
      for (let node: HTMLElement | null = el.parentElement; node; node = node.parentElement) {
        const c = parse(getComputedStyle(node).backgroundColor)
        if (c.length >= 3 && (c.length < 4 || (c[3] ?? 1) > 0.5)) return c
      }
      return [255, 255, 255]
    }
    const style = getComputedStyle(el)
    const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 1
    const ring = outline || (style.boxShadow !== 'none' && style.boxShadow !== '')
    const a = lum(parse(outline ? style.outlineColor : style.boxShadow.match(/rgba?\([^)]+\)/)?.[0] ?? style.color))
    const b = lum(background())
    const rect = el.getBoundingClientRect()
    return {
      tag: el.tagName.toLowerCase() + (el instanceof HTMLInputElement ? `[${el.type}]` : ''),
      name: (el.getAttribute('aria-label') || el.textContent || el.getAttribute('name') || el.id || '').trim().slice(0, 40),
      top: rect.top + window.scrollY,
      left: rect.left + window.scrollX,
      inMain: !!el.closest('main'),
      inDialog: !!el.closest('dialog[open]'),
      ring,
      ringContrast: Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 10) / 10,
    }
  })
}

const label = (s: Stop) => `${s.tag} "${s.name}"`

/** Put the sequential-focus starting point at the very top of the document, as on a fresh page load: blur alone
 * leaves it wherever the last click or autofocus was. */
async function fromTop(page: Page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    const probe = document.createElement('button')
    probe.dataset.focusProbe = ''
    document.body.prepend(probe)
    probe.focus()
  })
  await page.keyboard.press('Tab')
  await page.evaluate(() => document.querySelector('[data-focus-probe]')?.remove())
}

/** Tab through the page from the top: every stop shows a ring with 3:1 contrast, order inside <main> runs top to
 * bottom (a jump up and to the left is out of visual order), and Shift+Tab walks back to the first stop (no trap). */
export async function tabWalk(page: Page, steps = 40): Promise<string[]> {
  const problems: string[] = []
  await fromTop(page)
  const stops: Stop[] = []
  let offEnd = false
  for (let i = 0; i < steps; i++) {
    if (i > 0) await page.keyboard.press('Tab')
    const stop = await focused(page)
    if (!stop) {
      offEnd = true // walked off the end of the document, into the browser
      break
    }
    stops.push(stop)
    if (!stop.ring) problems.push(`no visible focus indicator on ${label(stop)} (2.4.7)`)
    else if (stop.ringContrast < 3) problems.push(`focus indicator contrast ${stop.ringContrast}:1 on ${label(stop)} (1.4.11)`)
  }
  for (const [i, next] of stops.entries()) {
    const prev = stops[i - 1]
    if (prev && prev.inMain && next.inMain && next.top < prev.top - 40 && next.left < prev.left - 40)
      problems.push(`tab order jumps back up from ${label(prev)} to ${label(next)} (2.4.3)`)
  }
  const first = stops[0]
  if (first && stops.length > 2) {
    for (let i = offEnd ? 0 : 1; i < stops.length; i++) await page.keyboard.press('Shift+Tab')
    const back = await focused(page)
    if (!back || back.name !== first.name || back.tag !== first.tag)
      problems.push(`Shift+Tab did not return to the first stop ${label(first)} (2.1.2)`)
  }
  if (stops.length === 0) problems.push('nothing on the page takes keyboard focus (2.1.1)')
  return problems
}

/** The first Tab lands on the skip link, and following it moves focus into <main> (2.4.1). */
export async function skipLink(page: Page): Promise<string[]> {
  await fromTop(page)
  const first = await focused(page)
  if (!first || !/skip to/i.test(first.name)) return [`first Tab stop is ${first ? label(first) : 'nothing'}, not a skip link (2.4.1)`]
  if (!first.ring) return ['the skip link has no visible focus indicator (2.4.7)']
  await page.keyboard.press('Enter')
  const inMain = await page.evaluate(() => !!document.activeElement?.closest('main'))
  return inMain ? [] : ['following the skip link does not move focus into <main> (2.4.1)']
}

/** One <h1>, a page title that names the page, header cells in every table (1.3.1, 2.4.2). */
export async function structure(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = []
    const h1 = [...document.querySelectorAll('h1')].filter((h) => h.getClientRects().length > 0)
    if (h1.length !== 1) problems.push(`${h1.length} visible <h1> elements, expected 1 (1.3.1)`)
    const heading = (h1[0]?.textContent ?? '').trim()
    if (!document.title.trim()) problems.push('empty page <title> (2.4.2)')
    else if (heading && !document.title.includes(heading.slice(0, 20)))
      problems.push(`title "${document.title}" does not name the page "${heading}" (2.4.2)`)
    document.querySelectorAll('table').forEach((t, i) => {
      if (t.getClientRects().length && !t.querySelector('th')) problems.push(`table ${i + 1} has no header cells (1.3.1)`)
    })
    return problems
  })
}

/** Pointer targets of at least 24 by 24 CSS px, or spaced so a 24 px circle on each touches no other (2.5.8).
 * Inline links in text are exempt; a checkbox or radio counts with its label. */
export async function targetSize(page: Page, scope = 'body'): Promise<string[]> {
  return page.evaluate((scope) => {
    const root = document.querySelector(scope) ?? document.body
    const nodes = [...root.querySelectorAll<HTMLElement>('a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab]')]
    const targets = nodes
      .filter((el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')
      .filter((el) => !el.closest('details:not([open]) > :not(summary)')) // laid out but not shown
      .filter((el) => !(el.tagName === 'A' && getComputedStyle(el).display === 'inline'))
      .map((el) => {
        let r = el.getBoundingClientRect()
        const box = el as HTMLInputElement
        if ((box.type === 'checkbox' || box.type === 'radio') && box.labels?.[0]) {
          const l = box.labels[0].getBoundingClientRect()
          r = new DOMRect(Math.min(r.left, l.left), Math.min(r.top, l.top), 0, 0)
          r.width = Math.max(box.getBoundingClientRect().right, l.right) - r.left
          r.height = Math.max(box.getBoundingClientRect().bottom, l.bottom) - r.top
        }
        return { el, r }
      })
      .filter(({ r }) => r.width > 1 && r.height > 1) // visually hidden (the skip link at rest)
    const problems: string[] = []
    for (const { el, r } of targets) {
      if (r.width >= 24 - 0.5 && r.height >= 24 - 0.5) continue
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      const crowded = targets.some(({ el: other, r: o }) => {
        if (other === el || other.contains(el) || el.contains(other)) return false
        const dx = Math.max(o.left - cx, 0, cx - o.right)
        const dy = Math.max(o.top - cy, 0, cy - o.bottom)
        return Math.hypot(dx, dy) < 12
      })
      if (crowded) {
        const name = (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 30)
        problems.push(`target "${name}" is ${Math.round(r.width)}x${Math.round(r.height)} px and crowded (2.5.8)`)
      }
    }
    return problems
  }, scope)
}

/** No page-level horizontal scroll at 320 CSS px (1.4.10) or at 640 px, which is 1280 px at 200% zoom (1.4.4). */
export async function reflow(page: Page): Promise<string[]> {
  const problems: string[] = []
  const original = page.viewportSize()
  for (const width of [320, 640]) {
    await page.setViewportSize({ width, height: 720 })
    await page.waitForTimeout(150)
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    if (over > 1) problems.push(`horizontal page scroll of ${over} px at ${width} px wide (${width === 320 ? '1.4.10' : '1.4.4'})`)
  }
  if (original) await page.setViewportSize(original)
  return problems
}

/** A dialog opened from the keyboard takes focus, keeps Tab inside, closes on Escape and returns focus to its
 * opener (2.4.3, 2.1.2). */
export async function dialogKeyboard(page: Page, opener: Locator, dialog: Locator): Promise<string[]> {
  const problems: string[] = []
  await opener.focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await page.waitForTimeout(100)
  if (!(await page.evaluate(() => !!document.activeElement?.closest('dialog[open]'))))
    problems.push('focus did not move into the dialog on open (2.4.3)')
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab')
    await page.waitForTimeout(20) // date and time fields settle :focus-visible a frame after the key
    const stop = await focused(page)
    if (stop && !stop.inDialog) {
      problems.push(`Tab left the open dialog for ${label(stop)} (2.4.3)`)
      break
    }
    if (stop && !stop.ring) problems.push(`no visible focus indicator on ${label(stop)} in the dialog (2.4.7)`)
  }
  await page.keyboard.press('Escape')
  if (await dialog.isVisible()) problems.push('Escape did not close the dialog')
  else if (!(await opener.evaluate((el) => el === document.activeElement)))
    problems.push('focus did not return to the control that opened the dialog (2.4.3)')
  return [...new Set(problems)]
}

/** The whole page audit for a route: structure, targets, keyboard walk, reflow. */
export async function auditRoute(page: Page, name: string, { skip = true } = {}): Promise<string[]> {
  await settled(page)
  const found = [
    ...(await structure(page)),
    ...(await targetSize(page)),
    ...(skip ? await skipLink(page) : []),
    ...(await tabWalk(page)),
    ...(await reflow(page)),
  ]
  return [...new Set(found)].map((p) => `${name}: ${p}`)
}
