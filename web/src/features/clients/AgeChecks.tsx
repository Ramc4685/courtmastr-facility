import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useAuth } from '../../lib/auth'
import { formatDate, formatDateTime, fullName } from '../../lib/format'

/** Only the confirm action confirms an age; any other date change leaves it unconfirmed (clients README). */
export const CONFIRM_AGE = 'clients.client.confirm_age'
const QUEUE = ['clients', 'age-reviews'] as const

/** "Age not confirmed" on the client record, with the one-time staff check for holders of the key. */
export function AgeCheckBadge({ client }: { client: Schemas['ClientOut'] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [birthOn, setBirthOn] = useState(client.birth_on ?? '')
  const confirm = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/age-confirmation', { path: { client_id: client.id }, body: { birth_on: birthOn || null } }),
    onSuccess: () => {
      setOpen(false)
      void qc.invalidateQueries({ queryKey: ['clients'] })
    },
  })
  if (client.age_confirmed) return null
  return (
    <>
      <Badge tone="warning">Age not confirmed</Badge>
      {can(CONFIRM_AGE) && !client.merged_into_id && !client.erased_at && (
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Confirm age
        </Button>
      )}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Confirm age"
        description="Check the date of birth against an ID. This is a one-time check; the client's entry code is released once it is done."
        footer={
          <Button loading={confirm.isPending} disabled={!birthOn} onClick={() => confirm.mutate()}>
            Confirm age
          </Button>
        }
      >
        <Input label="Date of birth" type="date" required value={birthOn} error={fieldErrors(confirm.error).birth_on} onChange={(e) => setBirthOn(e.target.value)} />
        {confirm.error && !fieldErrors(confirm.error).birth_on && (
          <p role="alert" className="mt-2 text-danger">
            {confirm.error.message}
          </p>
        )}
      </Dialog>
    </>
  )
}

const columns: Column<Schemas['AgeReviewItem']>[] = [
  { header: 'Client', cell: (r) => <Link className="font-medium text-primary hover:underline" to={`/clients/${r.id}`}>{fullName(r)}</Link> },
  { header: 'Date of birth', cell: (r) => (r.birth_on ? formatDate(r.birth_on) : 'Hidden') },
  { header: 'First booking', cell: (r) => (r.earliest_booking_at ? formatDateTime(r.earliest_booking_at) : 'No booking yet') },
  { header: 'Joined', cell: (r) => formatDate(r.created_at.slice(0, 10)) },
]

/** The staff queue of self-declared birth dates waiting for the one-time check, people with a booking first. */
export function AgeChecksPage() {
  const paging = useKeysetQuery(QUEUE, (cursor) => api.get('/api/v1/client-age-reviews', { query: { cursor } }))
  return (
    <>
      <PageHeader title="Age checks" description="Clients who entered their own date of birth. Confirm each once against an ID; people with a booking come first." />
      <Table caption="Clients waiting for an age check" columns={columns} rowKey={(r) => r.id} paging={paging} empty={<EmptyState title="No one is waiting for an age check" />} />
    </>
  )
}

/** Dashboard count; hidden from staff without the key and when nobody is waiting. */
export function AgeChecksCard() {
  const { can } = useAuth()
  const count = useQuery({
    queryKey: [...QUEUE, 'total'],
    queryFn: () => api.get('/api/v1/client-age-reviews', { query: { limit: 1, include: 'total' } }),
    enabled: can(CONFIRM_AGE),
  })
  const total = count.data?.page.total ?? 0
  if (!total) return null
  return (
    <Card title="Age checks" className="mb-6">
      <p>
        <Link className="font-medium text-primary hover:underline" to="/clients/age-checks">
          {total === 1 ? '1 client is' : `${total} clients are`} waiting for an age check
        </Link>
      </p>
    </Card>
  )
}
