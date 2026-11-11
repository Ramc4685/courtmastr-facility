import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime, formatMoney } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { programError, useGroupFees, useGroupOptions, type Checkout } from './queries'

/** Staff registration basket: hold places for several clients and programs, then confirm them together
 * (one invoice for the payer). Held places lapse at the basket's expiry. */
export function BasketPage() {
  const { location } = useWorkingLocation()
  const qc = useQueryClient()
  const toast = useToast()
  const groups = useGroupOptions(location?.id)
  const [basket, setBasket] = useState<Checkout | null>(null)
  const [payer, setPayer] = useState<ClientSummary | null>(null)
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [groupId, setGroupId] = useState('')
  const [feeId, setFeeId] = useState('')
  const fees = useGroupFees(groupId || undefined)
  const activeFees = (fees.data ?? []).filter((f) => f.is_active)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['program-group'] })
    void qc.invalidateQueries({ queryKey: ['program-groups'] })
  }

  const start = useMutation({
    mutationFn: () => api.post('/api/v1/registration-checkouts', { body: { location_id: location?.id ?? '', payer_client_id: payer?.id ?? null } }),
    onSuccess: setBasket,
  })
  // The first item opens the basket, so staff never face an empty "start" step.
  const add = useMutation({
    mutationFn: async () => {
      const open = basket ?? (await start.mutateAsync())
      return api.post('/api/v1/registration-checkouts/{checkout_id}/items', {
        path: { checkout_id: open.id },
        body: { program_group_id: groupId, client_id: client?.id ?? '', program_fee_id: feeId || null },
      })
    },
    onSuccess: (b) => {
      setBasket(b)
      setClient(null)
      setFeeId('')
    },
  })
  const remove = useMutation({
    mutationFn: (itemId: string) => api.delete('/api/v1/registration-checkouts/{checkout_id}/items/{item_id}', { path: { checkout_id: basket?.id ?? '', item_id: itemId } }),
    onSuccess: setBasket,
    onError: (e) => toast('error', programError(e)),
  })
  const confirm = useMutation({
    mutationFn: () => api.post('/api/v1/registration-checkouts/{checkout_id}/confirm', { path: { checkout_id: basket?.id ?? '' } }),
    onSuccess: (b) => {
      setBasket(b)
      refresh()
      toast('success', 'Registrations confirmed.')
    },
  })
  const abandon = useMutation({
    mutationFn: () => api.post('/api/v1/registration-checkouts/{checkout_id}/abandon', { path: { checkout_id: basket?.id ?? '' } }),
    onSuccess: () => {
      setBasket(null)
      refresh()
      toast('success', 'Basket abandoned and the places released.')
    },
    onError: (e) => toast('error', programError(e)),
  })

  const done = basket?.status === 'completed'
  const error = add.error ?? confirm.error
  const lines = basket?.items ?? []
  return (
    <>
      <PageHeader title="Registration basket" description="Hold places for one or more clients, then confirm them together." actions={<Link to="/programs" className="inline-flex h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-surface-2">Back to programs</Link>} />
      {done ? (
        <Card>
          <EmptyState
            title="Registrations confirmed"
            action={
              <div className="flex gap-2">
                {basket.invoice_id && (
                  <Link to={`/billing/invoices/${basket.invoice_id}`} className="inline-flex h-10 items-center rounded bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover">
                    Open the invoice
                  </Link>
                )}
                <Button variant="secondary" onClick={() => setBasket(null)}>
                  Start another basket
                </Button>
              </div>
            }
          >
            {basket.items.length} {basket.items.length === 1 ? 'place' : 'places'} confirmed, {formatMoney(basket.total_minor)} in total.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Card title="Add a place">
            <form
              className="space-y-4"
              onSubmit={(ev) => {
                ev.preventDefault()
                add.mutate()
              }}
            >
              <LocationSelect className="w-full" />
              {!basket && <ClientPicker label="Payer" value={payer} onChange={setPayer} hint="Optional. Leave empty when each client pays for themselves." />}
              <ClientPicker label="Client" value={client} onChange={setClient} required />
              <Select
                label="Program"
                value={groupId}
                placeholder="Choose a program"
                required
                onChange={(e) => {
                  setGroupId(e.target.value)
                  setFeeId('')
                }}
                options={(groups.data?.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
              />
              {groupId && (fees.isPending ? <LoadingState /> : <Select label="Fee" value={feeId} placeholder="Choose a fee" onChange={(e) => setFeeId(e.target.value)} options={activeFees.map((f) => ({ value: f.id, label: `${f.description}, ${formatMoney(f.amount_minor)}` }))} />)}
              <Button type="submit" disabled={!client || !groupId || !feeId} loading={add.isPending}>
                Hold a place
              </Button>
            </form>
          </Card>
          <Card title="Basket">
            {error && (
              <p role="alert" className="mb-3 text-danger">
                {programError(error)}
              </p>
            )}
            {lines.length === 0 ? (
              <p className="text-muted">Nothing held yet.</p>
            ) : (
              <div className="space-y-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Held places</caption>
                    <thead className="text-xs uppercase tracking-wide text-muted">
                      <tr>
                        {['Client', 'Program', 'Price', ''].map((h, i) => (
                          <th key={i} scope="col" className="py-2 font-semibold">
                            {h || <span className="sr-only">Actions</span>}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {lines.map((i) => (
                        <tr key={i.id}>
                          <td className="py-2 font-medium">{i.client_name}</td>
                          <td className="py-2">{i.program_group_name}</td>
                          <td className="py-2 tabular">{formatMoney(i.amount_minor)}</td>
                          <td className="py-2 text-right">
                            <Button size="sm" variant="ghost" aria-label={`Remove ${i.client_name} from ${i.program_group_name}`} onClick={() => remove.mutate(i.id)}>
                              Remove
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="flex items-center justify-between border-t border-border pt-3 font-semibold">
                  <span>Total</span>
                  <span className="tabular">{formatMoney(basket?.total_minor)}</span>
                </p>
                <p className="text-sm text-muted">
                  Places are held until <Badge tone="warning">{formatDateTime(basket?.expires_at, location?.time_zone)}</Badge>
                </p>
                {(basket?.missing_documents.length ?? 0) > 0 && (
                  <div role="status" className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
                    <p className="font-medium">Documents still to sign</p>
                    <ul className="mt-1 list-disc pl-5">
                      {basket?.missing_documents.map((d) => {
                        const item = lines.find((i) => i.client_id === d.client_id && i.program_group_id === d.program_group_id)
                        return <li key={d.binding_id}>{item ? `${item.client_name} for ${item.program_group_name}` : 'A client'} has not signed a required document.</li>
                      })}
                    </ul>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button loading={confirm.isPending} onClick={() => confirm.mutate()}>
                    Confirm registrations
                  </Button>
                  <Button variant="secondary" loading={abandon.isPending} onClick={() => abandon.mutate()}>
                    Abandon basket
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </>
  )
}
