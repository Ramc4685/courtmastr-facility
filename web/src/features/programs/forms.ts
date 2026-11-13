import { ApiError, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'

export type EventForm = Schemas['EventFormOut']
export type EventFormDetail = Schemas['EventFormDetail']
export type FormItem = Schemas['FormQuestion'] | Schemas['FormTopic']
export type FormQuestion = Schemas['FormQuestion']
export type FormInventory = Schemas['FormInventoryOut']
export type FormSubmission = Schemas['FormSubmissionOut']
export type FormSubmissionDetail = Schemas['FormSubmissionDetail']
export type PublicForm = Schemas['PublicForm']
export type PublicFormItem = Schemas['PublicFormItem']
export type FormAnswerIn = Schemas['FormAnswerIn']

export const FORM_STATE: Record<string, { label: string; tone: Tone }> = {
  draft: { label: 'Draft', tone: 'neutral' },
  not_yet_open: { label: 'Opens soon', tone: 'info' },
  open: { label: 'Open', tone: 'success' },
  full_waitlist: { label: 'Full, wait list open', tone: 'warning' },
  full: { label: 'Full', tone: 'danger' },
  closed: { label: 'Closed', tone: 'neutral' },
}
export const SUBMISSION_TONE: Record<string, Tone> = { confirmed: 'success', waitlisted: 'warning', cancelled: 'neutral' }
export const QUESTION_TYPES: { value: FormQuestion['question_type']; label: string }[] = [
  { value: 'text_box', label: 'Text box' },
  { value: 'drop_down', label: 'Drop-down' },
  { value: 'radio', label: 'Pick one' },
  { value: 'checkbox', label: 'Pick any' },
  { value: 'purchase_quantity', label: 'Quantity to buy' },
]
export const CHOICE_TYPES = new Set(['drop_down', 'radio', 'checkbox'])
export const SUMMARY_KEYS = [
  { value: 'registrant', label: 'Registrations' },
  { value: 'revenue', label: 'Revenue' },
  { value: 'demographic', label: 'Demographics' },
  { value: 'answer', label: 'Answers' },
]

const ERROR_TEXT: Record<string, string> = {
  'draft-empty': 'Add at least one question or topic before publishing.',
  'form-is-template': 'A template is copied into new forms, not published.',
  'form-state': 'The form is not in a state that allows this.',
  'form-closed': 'This form is not taking registrations right now.',
  'form-full': 'The form is full.',
  'sold-out': 'One of the options you picked is sold out.',
  'sign-in-required': 'Sign in to register: this event has a price.',
  'coupon-not-allowed': 'This form does not take coupons.',
  'limit-below-sold': 'A cap cannot go below what has already sold.',
  'capacity-below-submitted': 'Capacity cannot go below the registrations already taken.',
  'already-cancelled': 'This registration is already cancelled.',
  'not-waitlisted': 'Only a wait-listed registration can be promoted.',
  'answer-required': 'Answer every required question.',
  'in-use': 'Programs use this classifier. Deactivate it instead.',
  'already-exists': 'That name is already taken.',
}

/** Our wording for the known problem codes, the server's detail otherwise. */
export const formError = (e: unknown): string =>
  (e instanceof ApiError && e.code && e.code !== 'validation-failed' && ERROR_TEXT[e.code]) || (e instanceof Error ? e.message : 'Something went wrong.')

/** A key for a new question or choice: short, unique within the form, and stable once saved. */
export const newKey = (prefix: string, taken: Iterable<string>) => {
  const used = new Set(taken)
  let n = 1
  while (used.has(`${prefix}${n}`)) n += 1
  return `${prefix}${n}`
}

/** The keys a stock cap may apply to: each choice (`question.choice`) and each quantity question. */
export const stockKeys = (items: FormItem[]) =>
  items.flatMap((i) =>
    i.type !== 'question'
      ? []
      : i.question_type === 'purchase_quantity'
        ? [{ key: i.key, label: i.text }]
        : (i.choices ?? []).map((c) => ({ key: `${i.key}.${c.key}`, label: `${i.text}: ${c.text}` })),
  )

/** Whether a public form question is shown, given the choices picked so far (REG-16 dependencies). */
export const isShown = (item: PublicFormItem, picked: Record<string, string[]>) =>
  !item.depends_on || (picked[item.depends_on.question_key] ?? []).includes(item.depends_on.choice_key)

/** The running total of what is picked, in minor units. */
export const totalOf = (items: PublicFormItem[], picked: Record<string, string[]>, quantities: Record<string, number>) =>
  items.reduce((sum, i) => {
    if (i.type !== 'question' || !isShown(i, picked)) return sum
    if (i.question_type === 'purchase_quantity') return sum + (quantities[i.key] ?? 0) * (i.unit_price_minor ?? 0)
    return sum + i.choices.filter((c) => (picked[i.key] ?? []).includes(c.key)).reduce((s, c) => s + c.price_minor, 0)
  }, 0)

/** The answers payload for the shown questions only. */
export const answersOf = (items: PublicFormItem[], picked: Record<string, string[]>, texts: Record<string, string>, quantities: Record<string, number>): FormAnswerIn[] =>
  items
    .filter((i) => i.type === 'question' && isShown(i, picked))
    .map((i) =>
      i.question_type === 'text_box'
        ? { item_key: i.key, text_value: texts[i.key] ?? '', choice_keys: [] }
        : i.question_type === 'purchase_quantity'
          ? { item_key: i.key, quantity: quantities[i.key] ?? 0, choice_keys: [] }
          : { item_key: i.key, choice_keys: picked[i.key] ?? [] },
    )
