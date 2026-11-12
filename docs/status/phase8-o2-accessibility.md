# Phase 8 chip O2, part B: manual accessibility pass

Branch `claude/p8-o2-perf`, cut from `claude/phase8-wave7-5be825` at `2612e84`. Target: WCAG 2.1 AA, plus
2.5.8 Target Size (Minimum) from 2.2, which the brief's checklist names. axe already runs in every
Playwright spec; this pass covers what axe cannot judge, and keeps it as assertions so it does not rot.

## How it was checked

`web/e2e/a11y-keyboard.spec.ts` with the helpers in `web/e2e/a11y.ts`. Run it against a lane with the demo
seed: `make api` and `make web` in one checkout, then `cd web && pnpm exec playwright test a11y-keyboard`.

| Check | Criterion | How |
|---|---|---|
| Keyboard reach and order | 2.1.1, 2.4.3 | Tab from the top of the page (a probe resets the sequential-focus start), up to 40 stops; a stop inside `<main>` that jumps more than 40 px up and to the left is out of order |
| No keyboard trap | 2.1.2 | Shift+Tab back the same number of stops must land on the first one |
| Visible focus, and its contrast | 2.4.7, 1.4.11 | Every stop draws an outline or box-shadow, at 3:1 against the nearest opaque background, in light and dark |
| Skip link | 2.4.1 | The first Tab stop is "Skip to main content", and Enter puts focus inside `<main>` |
| Structure | 1.3.1, 2.4.2 | One visible `<h1>`, a `<title>` that contains it, header cells in every table |
| Target size | 2.5.8 | 24 by 24 px, or the spacing exception; inline text links are exempt, a checkbox or radio counts with its label |
| Reflow and zoom | 1.4.10, 1.4.4 | No page-level horizontal scroll at 320 px, nor at 640 px (1280 px at 200%) |
| Dialogs | 2.4.3, 2.1.2 | Opened by Enter, focus moves in, 25 Tabs stay inside with a visible ring, Escape closes, focus returns to the opener |
| Errors | 3.3.1, 4.1.3 | A field error sets `aria-invalid`, is the field's `aria-describedby` target, and sits in a polite live region |
| Reduced motion | 2.3.3 (AAA, kept as a guard) | With `prefers-reduced-motion: reduce` no transition is longer than 0.01 s |

Routes: sign-in (wrong password announced; the MFA code step and its error, with the API stubbed because the
demo tenant keeps MFA optional), the step-up dialog (stubbed `step-up-required` on `/roles`), dashboard,
schedule and the New booking dialog, clients list and profile, billing, an invoice and its Take payment
dialog, POS, check-in, Settings security, plan and privacy, the member portal home and its Book a rental
dialog. Settings import does not exist yet, so it is not covered.

## Fixed (small and local)

| Route | Element | Criterion | Fix |
|---|---|---|---|
| Every form | Field error text | 4.1.3 | `components/Field.tsx`: the error element is always mounted as a polite live region (visually hidden when empty), so an error that appears is announced |
| Every form with a checkbox | Checkbox and its label | 2.5.8 | `Checkbox` label padded to a 24 px target with a negative margin, so the layout does not move |
| `/portal/*` | Skip link | 2.4.1 | `<main id="portal-main" tabIndex={-1}>`: the link now moves focus into the page instead of only scrolling |
| `/portal/*` at 320 px | Nav inbox count | 1.4.10 | The visually hidden count escaped the nav's horizontal scroller (426 px page scroll); the nav links are now `relative` |
| `/schedule` at 320 px | Calendar toolbar | 1.4.10 | The toolbar row wraps (it scrolled the page 46 px) |
| Booking dialog and every date or time field | The picker button inside the field | 2.4.7 | Tab stops on the picker button, where only `:focus-within` matches the field, so the ring vanished; `index.css` adds the ring there |

## Left open

None found on the covered routes after the fixes (`KNOWN` in the spec is empty, so a regression fails it).
What the pass does not cover, stated plainly:

- Screen reader output was not listened to (VoiceOver or NVDA); the checks are DOM and keyboard level.
- The check-in desk's booking dialog, POS dialogs (refund, drawer) and the mobile app were not walked.
- Colour contrast of text is axe's job in the other specs and was not re-measured here.
- Target size is measured at the default desktop viewport only.
