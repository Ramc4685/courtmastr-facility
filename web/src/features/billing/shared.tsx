import { useQuery } from '@tanstack/react-query'
import { useId, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import type { Column } from '../../components/Table'
import { useMe } from '../../lib/auth'
import { fullName } from '../../lib/format'
import { formatMoney } from './money'

export const useCurrency = () => useMe().tenant.currency

export function Money({ minor, className }: { minor: number; className?: string }) {
  return <span className={`tabular-nums ${className ?? ''}`}>{formatMoney(minor, useCurrency())}</span>
}

export function StatusBadge({ map, value }: { map: Record<string, [string, Tone]>; value: string }) {
  const [label, tone] = map[value] ?? [value, 'neutral' as Tone]
  return <Badge tone={tone}>{label}</Badge>
}

export const useClient = (id: string | null | undefined) =>
  useQuery({
    queryKey: ['clients', 'one', id],
    queryFn: () => api.get('/api/v1/clients/{client_id}', { path: { client_id: id ?? '' } }),
    enabled: Boolean(id),
    staleTime: 60_000,
  })

/** A client's name, linked to their billing page. Names are fetched once per client and cached. */
export function ClientName({ id, link = true }: { id: string | null | undefined; link?: boolean }) {
  const client = useClient(id)
  if (!id) return <span className="text-muted">No client</span>
  const name = client.data ? fullName(client.data) : client.isError ? 'Unknown client' : '…'
  return link ? (
    <Link to={`/billing/clients/${id}`} className="font-medium text-primary underline-offset-2 hover:underline">
      {name}
    </Link>
  ) : (
    <span>{name}</span>
  )
}

export function useLocationRef(id: string | null | undefined) {
  return useMe().locations?.find((l) => l.id === id)
}

export function LocationSelect({ value, onChange, label = 'Location', allowAll = false, error }: { value: string; onChange: (v: string) => void; label?: string; allowAll?: boolean; error?: string }) {
  const locations = useMe().locations ?? []
  return (
    <Select
      label={label}
      value={value}
      error={error}
      onChange={(e) => onChange(e.target.value)}
      options={locations.map((l) => ({ value: l.id, label: l.name }))}
      placeholder={allowAll ? 'All locations' : undefined}
    />
  )
}

// Reference lists: one page of 200 covers them.
export const useRevenueCategories = () =>
  useQuery({ queryKey: ['billing', 'revenue-categories', 'all'], queryFn: () => api.get('/api/v1/revenue-categories', { query: { limit: 200 } }) })
export const useTaxes = () => useQuery({ queryKey: ['billing', 'taxes', 'all'], queryFn: () => api.get('/api/v1/taxes', { query: { limit: 200 } }) })
export const useTenderTypes = () => useQuery({ queryKey: ['billing', 'tender-types'], queryFn: () => api.get('/api/v1/tender-types') })
export const useProviderAccounts = (enabled = true) =>
  useQuery({ queryKey: ['billing', 'provider-accounts'], queryFn: () => api.get('/api/v1/provider-accounts'), enabled })

/** A plain table for lists that arrive whole (invoice lines, allocations), styled like the paged Table. */
export function ListTable<T>({ caption, columns, rows, rowKey, empty }: { caption: string; columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; empty: ReactNode }) {
  if (rows.length === 0) return <div className="rounded-lg border border-border bg-surface">{empty}</div>
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            {columns.map((c) => (
              <th key={c.header} scope="col" className={`px-4 py-2.5 font-semibold ${c.className ?? ''}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.header} className={`px-4 py-3 align-middle ${c.className ?? ''}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MoneyInput(props: Omit<Parameters<typeof Input>[0], 'type' | 'inputMode'>) {
  return <Input inputMode="decimal" autoComplete="off" {...props} />
}

/** The error of a failed mutation, shown at the top of a form when it is not about one field. */
export function FormError({ error }: { error: Error | null }) {
  if (!error || Object.keys(fieldErrors(error)).length) return null
  return (
    <p role="alert" className="text-danger">
      {error.message}
    </p>
  )
}

type FormDialogProps = {
  title: string
  description?: ReactNode
  submitLabel: string
  danger?: boolean
  busy?: boolean
  error?: Error | null
  onSubmit: () => void
  onClose: () => void
  children: ReactNode
  size?: 'md' | 'lg'
}

/** A dialog that is one form: Enter submits, the footer button submits, errors show at the top. */
export function FormDialog({ title, description, submitLabel, danger, busy, error = null, onSubmit, onClose, children, size }: FormDialogProps) {
  const formId = useId()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  return (
    <Dialog
      open
      size={size}
      title={title}
      description={description}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant={danger ? 'danger' : 'primary'} loading={busy}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="space-y-4">
        <FormError error={error} />
        {children}
      </form>
    </Dialog>
  )
}

export function TextArea({ label, value, onChange, error, hint, required }: { label: string; value: string; onChange: (v: string) => void; error?: string; hint?: string; required?: boolean }) {
  const id = useId()
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        value={value}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className="block w-full rounded border border-border bg-surface px-3 py-2 text-sm text-fg aria-[invalid=true]:border-danger"
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

/** Label / value pairs for detail headers. */
export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted">{k}</dt>
          <dd className="mt-0.5">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
