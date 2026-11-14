import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatMoney } from '../../lib/format'
import { AttemptFields, AttemptLock, checkPortalAttempt } from '../billing/attempt'
import { clientName, CouponField, NewCardField, useAttemptKey } from '../portal/shared'
import { FORM_STATE, answersOf, formError, isShown, totalOf, type PublicForm, type PublicFormItem } from './forms'

type Receipt = Schemas['PublicFormReceipt']
type Contact = { contact_name: string; contact_email: string; contact_phone: string }
type Answers = {
  picked: Record<string, string[]>
  texts: Record<string, string>
  quantities: Record<string, number>
}

function Question({ item, answers, set, error }: { item: PublicFormItem; answers: Answers; set: (a: Answers) => void; error?: string }) {
  const { picked, texts, quantities } = answers
  const text = `${item.text ?? ''}${item.required ? ' (required)' : ''}`
  const priced = (c: PublicFormItem['choices'][number]) =>
    `${c.text}${c.price_minor ? ` · ${formatMoney(c.price_minor)}` : ''}${c.sold_out ? ' · sold out' : c.remaining !== null ? ` · ${c.remaining} left` : ''}`
  const chosen = picked[item.key] ?? []
  const pick = (keys: string[]) => set({ ...answers, picked: { ...picked, [item.key]: keys } })
  if (item.question_type === 'text_box')
    return (
      <Input
        label={text}
        hint={item.hint ?? undefined}
        maxLength={item.max_length ?? undefined}
        required={item.required}
        error={error}
        value={texts[item.key] ?? ''}
        onChange={(e) => set({ ...answers, texts: { ...texts, [item.key]: e.target.value } })}
      />
    )
  if (item.question_type === 'purchase_quantity')
    return (
      <Input
        label={`${text}${item.unit_price_minor ? ` · ${formatMoney(item.unit_price_minor)} each` : ''}`}
        hint={item.sold_out ? 'Sold out.' : item.remaining !== null && item.remaining !== undefined ? `${item.remaining} left.` : (item.hint ?? undefined)}
        type="number"
        min={0}
        max={item.max_quantity ?? item.remaining ?? undefined}
        disabled={item.sold_out}
        error={error}
        value={String(quantities[item.key] ?? 0)}
        onChange={(e) => set({ ...answers, quantities: { ...quantities, [item.key]: Math.max(0, Number(e.target.value) || 0) } })}
      />
    )
  if (item.question_type === 'drop_down')
    return (
      <Select
        label={text}
        hint={item.hint ?? undefined}
        error={error}
        placeholder="Choose one"
        value={chosen[0] ?? ''}
        onChange={(e) => pick(e.target.value ? [e.target.value] : [])}
        options={item.choices.filter((c) => !c.sold_out).map((c) => ({ value: c.key, label: priced(c) }))}
      />
    )
  const multi = item.question_type === 'checkbox'
  return (
    <fieldset className="space-y-2" aria-describedby={error ? `${item.key}-error` : undefined}>
      <legend className="text-sm font-medium">{text}</legend>
      {item.hint && <p className="text-xs text-muted">{item.hint}</p>}
      {item.choices.map((c) =>
        multi ? (
          <Checkbox
            key={c.key}
            label={priced(c)}
            disabled={c.sold_out}
            checked={chosen.includes(c.key)}
            onChange={(e) => pick(e.target.checked ? [...chosen, c.key] : chosen.filter((k) => k !== c.key))}
          />
        ) : (
          <label key={c.key} className="flex items-center gap-2 text-sm">
            <input type="radio" name={item.key} value={c.key} disabled={c.sold_out} checked={chosen[0] === c.key} onChange={() => pick([c.key])} />
            {priced(c)}
          </label>
        ),
      )}
      {error && (
        <p id={`${item.key}-error`} className="text-sm text-danger">
          {error}
        </p>
      )}
    </fieldset>
  )
}

/** The fill-in form shared by the anonymous page and the portal. `portal` adds the registrant, card and coupon. */
function FormFill({ form, portal }: { form: PublicForm; portal: boolean }) {
  const [answers, setAnswers] = useState<Answers>({ picked: {}, texts: {}, quantities: {} })
  const [contact, setContact] = useState<Contact>({ contact_name: '', contact_email: '', contact_phone: '' })
  const [registrant, setRegistrant] = useState('')
  const [card, setCard] = useState('')
  const [coupon, setCoupon] = useState('')
  const attempt = useAttemptKey(portal ? `portal-form:${form.id}` : undefined, portal ? checkPortalAttempt : undefined)
  // Anonymous visitors have no portal session, so the household list loads only inside the portal.
  const clients = useQuery({ queryKey: ['portal', 'clients'], queryFn: () => api.get('/api/v1/portal/clients'), enabled: portal })
  const household = clients.data?.data ?? []
  const total = totalOf(form.items, answers.picked, answers.quantities)
  const shown = form.items.filter((i) => isShown(i, answers.picked))
  const submit = useMutation<Receipt, Error>({
    mutationFn: () => {
      const body = { ...contact, contact_phone: contact.contact_phone || null, answers: answersOf(form.items, answers.picked, answers.texts, answers.quantities) }
      return portal
        ? api.post('/api/v1/portal/form-submissions', {
            body: { ...body, form_id: form.id, registrant_client_id: registrant || household[0]?.id || '', method_token: total > 0 ? card || null : null, coupon_code: coupon || null },
            idempotencyKey: attempt.key,
          })
        : api.post('/api/v1/public/forms/{form_id}/submissions', { path: { form_id: form.id }, body })
    },
    onSettled: (_, error) => {
      if (portal) attempt.settle(error)
    },
  })
  const e = fieldErrors(submit.error)
  if (submit.data) {
    const r = submit.data
    return (
      <Card>
        <div role="status" className="space-y-2">
          <h2 className="text-lg font-semibold">{r.status === 'waitlisted' ? 'You are on the wait list' : 'You are registered'}</h2>
          <p>Confirmation number {r.confirmation_no}.</p>
          {r.total_minor > 0 && <p>Total {formatMoney(r.total_minor)}.</p>}
          {r.confirmation_message && <p>{r.confirmation_message}</p>}
        </div>
      </Card>
    )
  }
  if (form.state !== 'open' && form.state !== 'full_waitlist') {
    return (
      <Card>
        <p role="status">{form.closed_message || `${FORM_STATE[form.state]?.label ?? 'Closed'}: this form is not taking registrations right now.`}</p>
      </Card>
    )
  }
  const needsSignIn = !portal && total > 0
  const missing = submit.error instanceof ApiError && submit.error.code === 'answer-required'
  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault()
        if (!needsSignIn) submit.mutate()
      }}
    >
      {form.state === 'full_waitlist' && <p className="rounded border border-warning/40 bg-warning/10 px-3 py-2">This event is full. Registering puts you on the wait list.</p>}
      <AttemptLock attempt={attempt} />
      <AttemptFields attempt={attempt} className="space-y-5">
      {portal && household.length > 1 && (
        <Select
          label="Registering"
          value={registrant || household[0]?.id || ''}
          onChange={(ev) => setRegistrant(ev.target.value)}
          options={household.map((c) => ({ value: c.id, label: clientName(c) }))}
        />
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Input label="Your name" required autoComplete="name" error={e.contact_name} value={contact.contact_name} onChange={(ev) => setContact({ ...contact, contact_name: ev.target.value })} />
        <Input
          label="Email"
          type="email"
          required
          autoComplete="email"
          error={e.contact_email}
          value={contact.contact_email}
          onChange={(ev) => setContact({ ...contact, contact_email: ev.target.value })}
        />
        <Input label="Phone" type="tel" autoComplete="tel" error={e.contact_phone} value={contact.contact_phone} onChange={(ev) => setContact({ ...contact, contact_phone: ev.target.value })} />
      </div>
      {shown.map((item) =>
        item.type === 'topic' ? (
          <section key={item.key} className="space-y-1">
            {item.title && <h2 className="text-lg font-semibold">{item.title}</h2>}
            {item.body && <p className="whitespace-pre-line">{item.body}</p>}
          </section>
        ) : (
          <Question key={item.key} item={item} answers={answers} set={setAnswers} error={missing && item.required ? 'Answer this question.' : undefined} />
        ),
      )}
      <p className="text-lg font-semibold tabular" aria-live="polite">
        Total {formatMoney(total)}
      </p>
      {portal && total > 0 && (
        <>
          {form.allows_coupons && <CouponField subtotalMinor={total} onChange={setCoupon} />}
          <NewCardField value={card} onChange={setCard} />
        </>
      )}
      </AttemptFields>
      {submit.error && (
        <p role="alert" className="text-danger">
          {formError(submit.error)}
        </p>
      )}
      {needsSignIn ? (
        <p role="status" className="rounded border border-border bg-surface-2 px-3 py-2">
          Your choices have a price, so sign in to pay.{' '}
          <Link className="font-medium text-primary hover:underline" to={`/portal/forms/${form.id}`}>
            Sign in and register
          </Link>
        </p>
      ) : (
        <Button type="submit" loading={submit.isPending} disabled={portal && total > 0 && !card}>
          {attempt.locked ? 'Try again' : total > 0 ? `Register and pay ${formatMoney(total)}` : 'Register'}
        </Button>
      )}
    </form>
  )
}

function FormView({ portal }: { portal: boolean }) {
  const { id = '' } = useParams()
  const form = useQuery({ queryKey: ['public', 'form', id], queryFn: () => api.get('/api/v1/public/forms/{form_id}', { path: { form_id: id } }) })
  if (form.isPending) return <LoadingState />
  if (form.isError) return <ErrorState error={form.error} onRetry={() => form.refetch()} />
  const f = form.data
  // The tenant's own accent colour (REG-18) is data, not part of our palette.
  const accent = typeof f.theme.accent_color === 'string' ? f.theme.accent_color : undefined
  const when = f.event_starts_on ? `${formatDate(f.event_starts_on)}${f.event_ends_on && f.event_ends_on !== f.event_starts_on ? ` to ${formatDate(f.event_ends_on)}` : ''}` : undefined
  return (
    <div className="space-y-4 border-t-4 border-primary pt-4" style={accent ? { borderTopColor: accent } : undefined}>
      {f.has_header_image && <img src={`/api/v1/public/forms/${f.id}/header-image`} alt="" className="max-h-64 w-full rounded object-cover" />}
      <PageHeader title={f.event_name} description={when} />
      {f.event_text && <p className="whitespace-pre-line">{f.event_text}</p>}
      <FormFill form={f} portal={portal} />
    </div>
  )
}

/** The anonymous event form (REG-15, REG-20): free sign-ups without an account; priced choices ask for sign-in. */
export function PublicFormPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <FormView portal={false} />
    </main>
  )
}

/** The same form inside the portal: registers a household member and pays online through secure checkout. */
export function PortalFormPage() {
  return <FormView portal />
}
