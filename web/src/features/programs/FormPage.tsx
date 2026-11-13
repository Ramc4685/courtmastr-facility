import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, downloadFile, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { FileUpload } from '../../components/FileUpload'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney } from '../../lib/format'
import {
  CHOICE_TYPES,
  FORM_STATE,
  formError,
  newKey,
  QUESTION_TYPES,
  stockKeys,
  SUBMISSION_TONE,
  SUMMARY_KEYS,
  type EventFormDetail,
  type FormItem,
  type FormQuestion,
  type FormSubmission,
} from './forms'

const toMinor = (v: string) => (v.trim() === '' ? null : Math.round(Number(v) * 100))
const fromMinor = (v: number | null | undefined) => (v === null || v === undefined ? '' : (v / 100).toFixed(2))
const local = (v: string | null | undefined) => (v ? v.slice(0, 16) : '')
const itemsOf = (f: EventFormDetail) => ((f.draft ?? f.published)?.schema_doc as { items?: FormItem[] } | undefined)?.items ?? []

function useRefreshForm(id: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['form', id] })
    void qc.invalidateQueries({ queryKey: ['forms'] })
  }
}

// --- settings (REG-18 to REG-20, REG-24) ---

function SettingsTab({ form }: { form: EventFormDetail }) {
  const toast = useToast()
  const refresh = useRefreshForm(form.id)
  const [f, setF] = useState({
    name: form.name,
    event_name: form.event_name ?? '',
    event_text: form.event_text ?? '',
    event_starts_on: form.event_starts_on ?? '',
    event_ends_on: form.event_ends_on ?? '',
    opens_local: local(form.opens_local),
    closes_local: local(form.closes_local),
    capacity: form.capacity?.toString() ?? '',
    has_waitlist: form.has_waitlist,
    allows_coupons: form.allows_coupons,
    confirmation_message: form.confirmation_message ?? '',
    closed_message: form.closed_message ?? '',
    accent_color: (form.theme as { accent_color?: string } | null)?.accent_color ?? '',
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/forms/{form_id}', {
        path: { form_id: form.id },
        body: {
          name: f.name,
          event_name: f.event_name || null,
          event_text: f.event_text || null,
          event_starts_on: f.event_starts_on || null,
          event_ends_on: f.event_ends_on || null,
          opens_local: f.opens_local || null,
          closes_local: f.closes_local || null,
          capacity: f.capacity.trim() === '' ? null : Number(f.capacity),
          has_waitlist: f.has_waitlist,
          allows_coupons: f.allows_coupons,
          confirmation_message: f.confirmation_message || null,
          closed_message: f.closed_message || null,
          theme: f.accent_color ? { accent_color: f.accent_color, header_alignment: (form.theme as { header_alignment?: 'left' | 'center' | 'right' } | null)?.header_alignment ?? 'center' } : null,
        },
      }),
    onSuccess: () => {
      refresh()
      toast('success', 'Settings saved.')
    },
  })
  const removeHeader = useMutation({
    mutationFn: () => api.delete('/api/v1/forms/{form_id}/header-image', { path: { form_id: form.id } }),
    onSuccess: refresh,
  })
  const e = fieldErrors(save.error)
  return (
    <div className="space-y-6">
      <form
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        {save.error && Object.keys(e).length === 0 && (
          <p role="alert" className="text-danger sm:col-span-2">
            {formError(save.error)}
          </p>
        )}
        <Input label="Form name" value={f.name} required error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Input label="Event name" value={f.event_name} error={e.event_name} onChange={(ev) => set({ event_name: ev.target.value })} />
        <Input className="sm:col-span-2" label="Event description" value={f.event_text} error={e.event_text} onChange={(ev) => set({ event_text: ev.target.value })} />
        <Input label="Event starts" type="date" value={f.event_starts_on} error={e.event_starts_on} onChange={(ev) => set({ event_starts_on: ev.target.value })} />
        <Input label="Event ends" type="date" value={f.event_ends_on} error={e.event_ends_on} onChange={(ev) => set({ event_ends_on: ev.target.value })} />
        <Input
          label="Opens at"
          type="datetime-local"
          hint="Location time. Blank opens on publish."
          value={f.opens_local}
          error={e.opens_local}
          onChange={(ev) => set({ opens_local: ev.target.value })}
        />
        <Input
          label="Closes at"
          type="datetime-local"
          hint="Location time. Blank stays open until closed."
          value={f.closes_local}
          error={e.closes_local}
          onChange={(ev) => set({ closes_local: ev.target.value })}
        />
        <Input label="Capacity" type="number" min={1} hint="Blank for no limit." value={f.capacity} error={e.capacity} onChange={(ev) => set({ capacity: ev.target.value })} />
        <Input
          label="Accent colour"
          hint="A hex colour such as #1d4ed8."
          value={f.accent_color}
          error={e['theme.accent_color'] ?? e.theme}
          onChange={(ev) => set({ accent_color: ev.target.value })}
        />
        <Checkbox label="Take a wait list when full" checked={f.has_waitlist} onChange={(ev) => set({ has_waitlist: ev.target.checked })} />
        <Checkbox label="Accept coupons" checked={f.allows_coupons} onChange={(ev) => set({ allows_coupons: ev.target.checked })} />
        <Input
          className="sm:col-span-2"
          label="Confirmation message"
          value={f.confirmation_message}
          error={e.confirmation_message}
          onChange={(ev) => set({ confirmation_message: ev.target.value })}
        />
        <Input className="sm:col-span-2" label="Closed message" value={f.closed_message} error={e.closed_message} onChange={(ev) => set({ closed_message: ev.target.value })} />
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save settings
          </Button>
        </div>
      </form>
      <Card title="Header image">
        <div className="space-y-3">
          <p className="text-sm text-muted">{form.has_header_image ? 'A header image is set.' : 'No header image yet.'}</p>
          <FileUpload
            label="Upload a header image"
            purpose="form_header"
            accept={['image/jpeg', 'image/png']}
            maxBytes={900_000}
            route="/api/v1/forms/{form_id}/header-image"
            path={{ form_id: form.id }}
            hint="JPEG or PNG, up to 900 KB."
            onUploaded={refresh}
          />
          {form.has_header_image && (
            <Button variant="secondary" loading={removeHeader.isPending} onClick={() => removeHeader.mutate()}>
              Remove header image
            </Button>
          )}
        </div>
      </Card>
    </div>
  )
}

// --- questions (REG-16) ---

function ChoiceRows({ q, label, onChange }: { q: FormQuestion; label: string; onChange: (q: FormQuestion) => void }) {
  const choices = q.choices ?? []
  const put = (ci: number, patch: Partial<(typeof choices)[number]>) => onChange({ ...q, choices: choices.map((x, i) => (i === ci ? { ...x, ...patch } : x)) })
  return (
    <fieldset className="space-y-2 sm:col-span-2">
      <legend className="text-sm font-medium">{label} choices</legend>
      {choices.map((c, ci) => (
        <div key={c.key} className="flex flex-wrap items-end gap-2">
          <Input className="flex-1" label={`${label} choice ${ci + 1}`} value={c.text} onChange={(ev) => put(ci, { text: ev.target.value })} />
          <Input
            className="w-32"
            label={`${label} choice ${ci + 1} price`}
            type="number"
            min={0}
            step="0.01"
            value={fromMinor(c.price_minor)}
            onChange={(ev) => put(ci, { price_minor: toMinor(ev.target.value) ?? 0 })}
          />
          <Button size="sm" variant="ghost" aria-label={`Remove ${label} choice ${ci + 1}`} onClick={() => onChange({ ...q, choices: choices.filter((_, i) => i !== ci) })}>
            Remove
          </Button>
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={() => onChange({ ...q, choices: [...choices, { key: newKey('c', choices.map((c) => c.key)), text: '', price_minor: 0 }] })}>
        Add choice
      </Button>
    </fieldset>
  )
}

type EditorProps = {
  item: FormItem
  index: number
  count: number
  questions: FormQuestion[]
  onChange: (i: FormItem) => void
  onMove: (by: number) => void
  onRemove: () => void
}

function ItemEditor({ item, index, count, questions, onChange, onMove, onRemove }: EditorProps) {
  const label = item.type === 'topic' ? `Topic ${index + 1}` : `Question ${index + 1}`
  const parents = questions.filter((q) => q.key !== item.key && CHOICE_TYPES.has(q.question_type))
  return (
    <li className="rounded border border-border p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" aria-label={`Move ${label} up`} disabled={index === 0} onClick={() => onMove(-1)}>
            Up
          </Button>
          <Button size="sm" variant="ghost" aria-label={`Move ${label} down`} disabled={index === count - 1} onClick={() => onMove(1)}>
            Down
          </Button>
          <Button size="sm" variant="ghost" aria-label={`Remove ${label}`} onClick={onRemove}>
            Remove
          </Button>
        </span>
      </div>
      {item.type === 'topic' ? (
        <div className="grid gap-3">
          <Input label={`${label} title`} value={item.title ?? ''} onChange={(ev) => onChange({ ...item, title: ev.target.value })} />
          <Input label={`${label} text`} value={item.body ?? ''} onChange={(ev) => onChange({ ...item, body: ev.target.value })} />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Input className="sm:col-span-2" label={`${label} text`} value={item.text} onChange={(ev) => onChange({ ...item, text: ev.target.value })} />
          <Select
            label={`${label} type`}
            value={item.question_type}
            options={QUESTION_TYPES}
            onChange={(ev) => {
              const question_type = ev.target.value as FormQuestion['question_type']
              const choices = CHOICE_TYPES.has(question_type) ? (item.choices?.length ? item.choices : [{ key: 'c1', text: '', price_minor: 0 }]) : []
              onChange({ ...item, question_type, choices, unit_price_minor: question_type === 'purchase_quantity' ? (item.unit_price_minor ?? 0) : null })
            }}
          />
          {item.question_type === 'purchase_quantity' && (
            <Input
              label={`${label} unit price`}
              type="number"
              min={0}
              step="0.01"
              value={fromMinor(item.unit_price_minor)}
              onChange={(ev) => onChange({ ...item, unit_price_minor: toMinor(ev.target.value) })}
            />
          )}
          {parents.length > 0 && (
            <Select
              label={`${label} shows only when`}
              value={item.depends_on ? `${item.depends_on.question_key}.${item.depends_on.choice_key}` : ''}
              placeholder="Always shown"
              onChange={(ev) => {
                const [question_key, choice_key] = ev.target.value.split('.')
                onChange({ ...item, depends_on: question_key && choice_key ? { question_key, choice_key } : null })
              }}
              options={parents.flatMap((q) => (q.choices ?? []).map((c) => ({ value: `${q.key}.${c.key}`, label: `${q.text}: ${c.text}` })))}
            />
          )}
          <div className="flex flex-wrap gap-4 sm:col-span-2">
            <Checkbox label={`${label} required`} checked={!!item.required} onChange={(ev) => onChange({ ...item, required: ev.target.checked })} />
            <Checkbox label={`${label} staff only`} checked={item.visibility === 'staff_only'} onChange={(ev) => onChange({ ...item, visibility: ev.target.checked ? 'staff_only' : 'shown' })} />
          </div>
          {CHOICE_TYPES.has(item.question_type) && <ChoiceRows q={item} label={label} onChange={onChange} />}
        </div>
      )}
    </li>
  )
}

function QuestionsTab({ form }: { form: EventFormDetail }) {
  const toast = useToast()
  const refresh = useRefreshForm(form.id)
  const [items, setItems] = useState<FormItem[]>(itemsOf(form))
  const keys = items.map((i) => i.key)
  const questions = items.filter((i): i is FormQuestion => i.type === 'question')
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/forms/{form_id}/draft', { path: { form_id: form.id }, body: { items } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Draft saved. Publish it to show registrants.')
    },
  })
  const move = (index: number, by: number) => {
    const next = [...items]
    const [it] = next.splice(index, 1)
    if (it) next.splice(index + by, 0, it)
    setItems(next)
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {form.draft
          ? `Editing draft version ${form.draft.version_no}.`
          : form.published
            ? 'Saving starts a new draft; the live form stays until you publish.'
            : 'Add questions, then publish.'}
      </p>
      {items.length === 0 ? (
        <EmptyState title="No questions yet">Add a question or an information topic.</EmptyState>
      ) : (
        <ol className="space-y-3" aria-label="Questions and topics">
          {items.map((item, i) => (
            <ItemEditor
              key={item.key}
              item={item}
              index={i}
              count={items.length}
              questions={questions}
              onChange={(next) => setItems(items.map((x, j) => (j === i ? next : x)))}
              onMove={(by) => move(i, by)}
              onRemove={() => setItems(items.filter((_, j) => j !== i))}
            />
          ))}
        </ol>
      )}
      {save.error && (
        <p role="alert" className="text-danger">
          {formError(save.error)}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => setItems([...items, { type: 'question', key: newKey('q', keys), question_type: 'text_box', text: '', required: false, visibility: 'shown', choices: [] }])}
        >
          Add question
        </Button>
        <Button variant="secondary" onClick={() => setItems([...items, { type: 'topic', key: newKey('t', keys), title: '', body: '' }])}>
          Add topic
        </Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>
          Save draft
        </Button>
      </div>
    </div>
  )
}

// --- stock (REG-17) ---

type CapRow = { limit: string; show: boolean; memo: string }

function StockTab({ form }: { form: EventFormDetail }) {
  const toast = useToast()
  const caps = useQuery({ queryKey: ['form', form.id, 'inventory'], queryFn: () => api.get('/api/v1/forms/{form_id}/inventory', { path: { form_id: form.id } }) })
  const options = stockKeys(itemsOf(form))
  const [rows, setRows] = useState<Record<string, CapRow> | null>(null)
  const current: Record<string, CapRow> =
    rows ?? Object.fromEntries((caps.data ?? []).filter((c) => c.is_enabled).map((c) => [c.item_key, { limit: String(c.limit_count), show: c.shows_count_publicly, memo: c.sold_out_memo ?? '' }]))
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/forms/{form_id}/inventory', {
        path: { form_id: form.id },
        body: {
          items: Object.entries(current)
            .filter(([, r]) => r.limit.trim() !== '')
            .map(([item_key, r]) => ({ item_key, limit_count: Number(r.limit), is_enabled: true, shows_count_publicly: r.show, sold_out_memo: r.memo || null })),
        },
      }),
    onSuccess: () => {
      void caps.refetch()
      setRows(null)
      toast('success', 'Stock caps saved.')
    },
  })
  if (caps.isPending) return <LoadingState />
  if (caps.isError) return <ErrorState error={caps.error} />
  if (options.length === 0) return <EmptyState title="Nothing to cap">Add a choice or a quantity question first.</EmptyState>
  const sold = Object.fromEntries((caps.data ?? []).map((c) => [c.item_key, c.sold_count]))
  const set = (key: string, patch: Partial<CapRow>) => setRows({ ...current, [key]: { limit: '', show: false, memo: '', ...current[key], ...patch } })
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-border" aria-label="Stock caps">
        {options.map((o) => (
          <li key={o.key} className="grid gap-3 py-3 sm:grid-cols-4 sm:items-end">
            <p className="font-medium sm:col-span-4">
              {o.label} <span className="text-sm font-normal text-muted">({sold[o.key] ?? 0} sold)</span>
            </p>
            <Input label={`${o.label} limit`} type="number" min={0} hint="Blank for no cap." value={current[o.key]?.limit ?? ''} onChange={(ev) => set(o.key, { limit: ev.target.value })} />
            <Input className="sm:col-span-2" label={`${o.label} sold-out message`} value={current[o.key]?.memo ?? ''} onChange={(ev) => set(o.key, { memo: ev.target.value })} />
            <Checkbox label={`Show ${o.label} count left`} checked={current[o.key]?.show ?? false} onChange={(ev) => set(o.key, { show: ev.target.checked })} />
          </li>
        ))}
      </ul>
      {save.error && (
        <p role="alert" className="text-danger">
          {formError(save.error)}
        </p>
      )}
      <Button loading={save.isPending} onClick={() => save.mutate()}>
        Save stock caps
      </Button>
    </div>
  )
}

// --- registrations (REG-21, REG-24) ---

type Edits = { contact_name?: string; contact_email?: string; contact_phone?: string; texts: Record<string, string> }

function SubmissionDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const detail = useQuery({ queryKey: ['form-submission', id], queryFn: () => api.get('/api/v1/form-submissions/{form_submission_id}', { path: { form_submission_id: id } }) })
  const [edits, setEdits] = useState<Edits>({ texts: {} })
  const [reverse, setReverse] = useState(false)
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['form-submissions'] })
    void qc.invalidateQueries({ queryKey: ['form-submission', id] })
    void qc.invalidateQueries({ queryKey: ['form'] })
    toast('success', message)
  }
  const path = { form_submission_id: id }
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/form-submissions/{form_submission_id}', {
        path,
        body: { contact_name: edits.contact_name, contact_email: edits.contact_email, contact_phone: edits.contact_phone, text_answers: edits.texts },
      }),
    onSuccess: () => done('Registration saved.'),
  })
  const cancel = useMutation({
    mutationFn: () => api.post('/api/v1/form-submissions/{form_submission_id}/cancel', { path, body: { reverse_charges: reverse } }),
    onSuccess: () => done('Registration cancelled.'),
  })
  const promote = useMutation({
    mutationFn: () => api.post('/api/v1/form-submissions/{form_submission_id}/promote', { path }),
    onSuccess: () => done('Registration confirmed.'),
  })
  const error = save.error ?? cancel.error ?? promote.error
  const s = detail.data
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={s ? `Registration ${s.confirmation_no}` : 'Registration'}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      }
    >
      {detail.isPending ? (
        <LoadingState />
      ) : detail.isError || !s ? (
        <ErrorState error={detail.error} />
      ) : (
        <div className="space-y-4">
          <p className="flex flex-wrap items-center gap-2">
            <Badge tone={SUBMISSION_TONE[s.status]}>{s.status}</Badge>
            <span className="text-sm text-muted">
              {formatDateTime(s.submitted_at)} · {formatMoney(s.total_minor)}
            </span>
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Input label="Contact name" defaultValue={s.contact_name} onChange={(ev) => setEdits({ ...edits, contact_name: ev.target.value })} />
            <Input label="Contact email" type="email" defaultValue={s.contact_email} onChange={(ev) => setEdits({ ...edits, contact_email: ev.target.value })} />
            <Input label="Contact phone" defaultValue={s.contact_phone ?? ''} onChange={(ev) => setEdits({ ...edits, contact_phone: ev.target.value })} />
          </div>
          <dl className="divide-y divide-border">
            {s.answers.map((a) => (
              <div key={`${a.item_key}-${a.choice_key ?? ''}`} className="grid gap-1 py-2 sm:grid-cols-3">
                <dt className="text-sm text-muted">{a.label}</dt>
                <dd className="sm:col-span-2">
                  {a.text_value !== null && a.text_value !== undefined ? (
                    <Input label={`Answer: ${a.label}`} defaultValue={a.text_value} onChange={(ev) => setEdits({ ...edits, texts: { ...edits.texts, [a.item_key]: ev.target.value } })} />
                  ) : (
                    `${a.quantity ? `Quantity ${a.quantity}` : `Picked ${a.choice_key ?? ''}`.trim()}${a.amount_minor ? ` · ${formatMoney(a.amount_minor)}` : ''}`
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {error && (
            <p role="alert" className="text-danger">
              {formError(error)}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {can('programs.registration.update') && (
              <Button loading={save.isPending} onClick={() => save.mutate()}>
                Save changes
              </Button>
            )}
            {can('programs.registration.update') && s.status === 'waitlisted' && (
              <Button variant="secondary" loading={promote.isPending} onClick={() => promote.mutate()}>
                Confirm from wait list
              </Button>
            )}
            {can('programs.registration.cancel') && s.status !== 'cancelled' && (
              <>
                {s.total_minor > 0 && can('billing.charge.reverse') && <Checkbox label="Reverse charges" checked={reverse} onChange={(ev) => setReverse(ev.target.checked)} />}
                <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>
                  Cancel registration
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </Dialog>
  )
}

function RegistrationsTab({ form }: { form: EventFormDetail }) {
  const { can } = useAuth()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const paging = useKeysetQuery(['form-submissions', form.id, q, status], (cursor) =>
    api.get('/api/v1/form-submissions', { query: { form_id: form.id, q: q.trim() || undefined, status: status || undefined, cursor, limit: 50 } }),
  )
  const exportCsv = useMutation({
    mutationFn: () => downloadFile('/api/v1/forms/{form_id}/exports', { path: { form_id: form.id } }, 'registrations.csv', 'POST'),
    onError: (e) => toast('error', formError(e)),
  })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Input className="w-56" label="Search registrations" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select
          className="w-44"
          label="Registration status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: '', label: 'Any' },
            { value: 'confirmed', label: 'Confirmed' },
            { value: 'waitlisted', label: 'Wait list' },
            { value: 'cancelled', label: 'Cancelled' },
          ]}
        />
        {can('programs.registration.export') && (
          <Button variant="secondary" loading={exportCsv.isPending} onClick={() => exportCsv.mutate()}>
            Export CSV
          </Button>
        )}
      </div>
      <Table<FormSubmission>
        caption="Registrations"
        paging={paging}
        rowKey={(s) => s.id}
        empty={<EmptyState title="No registrations yet" />}
        columns={[
          {
            header: 'No.',
            cell: (s) => (
              <Button size="sm" variant="ghost" aria-label={`Open registration ${s.confirmation_no}`} onClick={() => setOpen(s.id)}>
                {s.confirmation_no}
              </Button>
            ),
          },
          { header: 'Name', cell: (s) => s.contact_name },
          { header: 'Email', cell: (s) => s.contact_email },
          { header: 'Submitted', cell: (s) => formatDateTime(s.submitted_at) },
          { header: 'Total', cell: (s) => <span className="tabular">{formatMoney(s.total_minor)}</span> },
          { header: 'Status', cell: (s) => <Badge tone={SUBMISSION_TONE[s.status]}>{s.status}</Badge> },
        ]}
      />
      {open && <SubmissionDialog id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

// --- summaries (REG-22) ---

function SummariesTab({ form }: { form: EventFormDetail }) {
  const [key, setKey] = useState('registrant')
  const report = useQuery({
    queryKey: ['form', form.id, 'summary', key],
    queryFn: () => api.get('/api/v1/forms/{form_id}/summaries/{summary_key}', { path: { form_id: form.id, summary_key: key } }),
  })
  const title = SUMMARY_KEYS.find((k) => k.value === key)?.label ?? key
  return (
    <div className="space-y-4">
      <Select className="w-56" label="Summary" value={key} onChange={(e) => setKey(e.target.value)} options={SUMMARY_KEYS} />
      {report.isPending ? (
        <LoadingState />
      ) : report.isError ? (
        <ErrorState error={report.error} />
      ) : report.data.rows.length === 0 ? (
        <EmptyState title="Nothing to summarise yet" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{title} summary</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="px-3 py-2">
                  Group
                </th>
                <th scope="col" className="px-3 py-2">
                  Item
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Count
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {report.data.rows.map((r, i) => (
                <tr key={`${r.group}-${r.label}-${i}`} className="border-b border-border last:border-0">
                  <td className="px-3 py-2">{r.group}</td>
                  <td className="px-3 py-2">{r.label}</td>
                  <td className="tabular px-3 py-2 text-right">{r.count}</td>
                  <td className="tabular px-3 py-2 text-right">{r.amount_minor ? formatMoney(r.amount_minor) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const ACTED = { publish: 'Form published.', close: 'Form closed.', reopen: 'Form reopened.' } as const
type Verb = keyof typeof ACTED

/** One event form: settings, questions, stock, registrations and summaries (REG-15 to REG-24). */
export function FormPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const refresh = useRefreshForm(id)
  const toast = useToast()
  const form = useQuery({ queryKey: ['form', id], queryFn: () => api.get('/api/v1/forms/{form_id}', { path: { form_id: id } }) })
  const act = useMutation({
    mutationFn: (verb: Verb) =>
      verb === 'publish'
        ? api.post('/api/v1/forms/{form_id}/publish', { path: { form_id: id } })
        : verb === 'close'
          ? api.post('/api/v1/forms/{form_id}/close', { path: { form_id: id } })
          : api.post('/api/v1/forms/{form_id}/reopen', { path: { form_id: id } }),
    onSuccess: (_, verb) => {
      refresh()
      toast('success', ACTED[verb])
    },
    onError: (e) => toast('error', formError(e)),
  })
  if (form.isPending) return <LoadingState />
  if (form.isError) return <ErrorState error={form.error} onRetry={() => form.refetch()} />
  const f = form.data
  const state = FORM_STATE[f.effective_state]
  return (
    <>
      <PageHeader
        title={f.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {f.is_template ? <Badge tone="info">Template</Badge> : <Badge tone={state?.tone ?? 'neutral'}>{state?.label ?? f.effective_state}</Badge>}
            <span>{f.capacity ? `${f.submitted_count} of ${f.capacity} registered` : `${f.submitted_count} registered`}</span>
            {f.published && !f.is_template && (
              <Link className="text-primary hover:underline" to={`/forms/${f.id}`}>
                Open the public page
              </Link>
            )}
          </span>
        }
        actions={
          <>
            {f.draft && !f.is_template && (
              <Button loading={act.isPending && act.variables === 'publish'} onClick={() => act.mutate('publish')}>
                Publish
              </Button>
            )}
            {f.status === 'open' && (
              <Button variant="secondary" loading={act.isPending && act.variables === 'close'} onClick={() => act.mutate('close')}>
                Close form
              </Button>
            )}
            {f.status === 'closed' && (
              <Button variant="secondary" loading={act.isPending && act.variables === 'reopen'} onClick={() => act.mutate('reopen')}>
                Reopen form
              </Button>
            )}
          </>
        }
      />
      <p className="mb-4">
        <Link className="text-primary hover:underline" to="/programs/forms">
          All event forms
        </Link>
      </p>
      <Tabs
        label="Form sections"
        tabs={[
          { id: 'settings', label: 'Settings', content: <SettingsTab key={f.updated_at} form={f} /> },
          { id: 'questions', label: 'Questions', content: <QuestionsTab key={f.draft?.id ?? f.published?.id ?? 'none'} form={f} /> },
          { id: 'stock', label: 'Stock', content: <StockTab form={f} /> },
          ...(can('programs.form_response.read') ? [{ id: 'registrations', label: 'Registrations', content: <RegistrationsTab form={f} /> }] : []),
          ...(can('reporting.program.run') ? [{ id: 'summaries', label: 'Summaries', content: <SummariesTab form={f} /> }] : []),
        ]}
      />
    </>
  )
}
