import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import type { Sale } from './shared'

type Candidate = { id: string; display_name: string; member_number: string | null; primary_email: string | null; phone_mobile: string | null }

/** POS-08: create a client with a few fields and attach them to the open sale. A possible duplicate is shown
 *  first; the cashier attaches that client or confirms the person is new. */
export function QuickClientDialog({ sale, onSale, onClose }: { sale: Sale; onSale: (s: Sale) => void; onClose: () => void }) {
  const [f, setF] = useState({ first_name: '', last_name: '', primary_email: '', phone_mobile: '' })
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const body = (confirm_new: boolean) => ({
    version: sale.version,
    first_name: f.first_name,
    last_name: f.last_name,
    primary_email: f.primary_email || null,
    phone_mobile: f.phone_mobile || null,
    confirm_new,
  })
  const create = useMutation({
    mutationFn: (confirm: boolean) => api.post('/api/v1/pos-sales/{pos_sale_id}/quick-client', { path: { pos_sale_id: sale.id }, body: body(confirm) }),
    onSuccess: (s) => {
      onSale(s)
      onClose()
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'possible-duplicate') setCandidates((e.problem.candidates as Candidate[]) ?? [])
    },
  })
  const attach = useMutation({
    mutationFn: (id: string) => api.patch('/api/v1/pos-sales/{pos_sale_id}', { path: { pos_sale_id: sale.id }, body: { version: sale.version, client_id: id } }),
    onSuccess: (s) => {
      onSale(s)
      onClose()
    },
  })
  const errors = fieldErrors(create.error)
  const failure = create.error instanceof ApiError && create.error.code !== 'possible-duplicate' && !Object.keys(errors).length ? create.error.message : attach.error?.message
  return (
    <Dialog
      open
      onClose={onClose}
      title="New client"
      description="Add the person with a few details; the rest can wait for the profile."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          {candidates.length > 0 ? (
            <Button loading={create.isPending} onClick={() => create.mutate(true)}>
              Create a new client anyway
            </Button>
          ) : (
            <Button disabled={!f.first_name.trim() || !f.last_name.trim()} loading={create.isPending} onClick={() => create.mutate(false)}>
              Create and attach
            </Button>
          )}
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="First name" required value={f.first_name} error={errors.first_name} onChange={(e) => { setF({ ...f, first_name: e.target.value }); setCandidates([]) }} />
        <Input label="Last name" required value={f.last_name} error={errors.last_name} onChange={(e) => { setF({ ...f, last_name: e.target.value }); setCandidates([]) }} />
        <Input label="Email" type="email" value={f.primary_email} error={errors.primary_email} onChange={(e) => setF({ ...f, primary_email: e.target.value })} />
        <Input label="Mobile phone" type="tel" hint="International format, for example +15551234567" value={f.phone_mobile} error={errors.phone_mobile} onChange={(e) => setF({ ...f, phone_mobile: e.target.value })} />
      </div>
      {failure && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {failure}
        </p>
      )}
      {candidates.length > 0 && (
        <section aria-labelledby="dupes-heading" className="mt-4 space-y-2">
          <h3 id="dupes-heading" className="text-sm font-semibold">
            This person may already be a client
          </h3>
          <ul className="divide-y divide-border rounded border border-border">
            {candidates.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                <span>
                  <span className="font-medium">{c.display_name}</span>
                  <span className="ml-2 text-muted">{[c.member_number, c.primary_email, c.phone_mobile].filter(Boolean).join(' · ')}</span>
                </span>
                <Button size="sm" variant="secondary" loading={attach.isPending} onClick={() => attach.mutate(c.id)} aria-label={`Attach ${c.display_name}`}>
                  Attach
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Dialog>
  )
}
