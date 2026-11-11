import { useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { PageHeader } from '../../components/PageHeader'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { fullName } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useWorkingLocation } from '../scheduling/location'
import { checkInColumns } from './CheckInPage'
import { ALERT_LABEL, allCheckIns, CHANNEL, downloadCsv, RESULT, toCsv } from './queries'

/** One client's check-in history with a CSV export (CHK-19). */
export function HistoryPage() {
  const [client, setClient] = useState<ClientSummary | null>(null)
  return (
    <>
      <PageHeader title="Check-in history" description="Every visit of one client, at every location you work at." />
      <div className="mb-6 max-w-md">
        <ClientPicker label="Client" value={client} onChange={setClient} />
      </div>
      {client && <ClientCheckIns client={client} />}
    </>
  )
}

type Person = Pick<ClientSummary, 'id' | 'first_name' | 'last_name'>

/** Also the Check-ins tab of the client profile. */
export function ClientCheckIns({ client }: { client: Person }) {
  const { location } = useWorkingLocation()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const paging = useKeysetQuery(['check-ins', 'client', client.id], (cursor) =>
    api.get('/api/v1/check-ins', { query: { client_id: client.id, limit: 25, cursor } }),
  )
  const exportCsv = async () => {
    setBusy(true)
    try {
      const rows = await allCheckIns(client.id)
      const lines = rows.map((r) => [r.checked_in_at, r.local_on, RESULT[r.result]?.label ?? r.result, r.denial_reason ?? '', CHANNEL[r.channel] ?? r.channel, r.alert_codes.map((a) => ALERT_LABEL[a] ?? a).join('; ')])
      downloadCsv(`check-ins-${fullName(client).replace(/\W+/g, '-').toLowerCase()}.csv`, toCsv([['Checked in at (UTC)', 'Local date', 'Result', 'Denial reason', 'How', 'Alerts'], ...lines]))
    } catch {
      toast('error', 'The export failed. Try again.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-labelledby="history-heading">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="history-heading">{fullName(client)}</h2>
        <Button variant="secondary" onClick={exportCsv} loading={busy}>Export CSV</Button>
      </div>
      <Table caption={`Check-ins of ${fullName(client)}`} columns={checkInColumns(location?.time_zone, false)} rowKey={(r) => r.id} paging={paging} empty={<p className="p-6 text-muted">No check-ins yet.</p>} />
    </section>
  )
}
