import { useMutation, useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { formatDateTime } from '../../lib/format'

type Code = Schemas['PortalEntryCodeOut']

/** Door codes of the household's upcoming bookings, with "Open the door" inside the window (CHK-16). Renders
 * nothing when there are none. `zoneOf` gives a location's time zone. `showHeld={false}`: the page already shows
 * the age-check notice (the same words), so held lines are left out rather than said twice. */
export function PortalEntryCodes({ zoneOf, showHeld = true }: { zoneOf: (locationId: string) => string | undefined; showHeld?: boolean }) {
  const codes = useQuery({ queryKey: ['portal', 'entry-codes'], queryFn: () => api.get('/api/v1/portal/entry-codes'), refetchInterval: 60_000 })
  const rows = (codes.data?.data ?? []).filter((c) => showHeld || c.code !== null)
  if (!rows.length) return null
  return (
    <section aria-labelledby="door-codes" className="mb-6 rounded-lg border border-border bg-surface p-4">
      <h2 id="door-codes" className="mb-2">Door codes</h2>
      <ul className="divide-y divide-border">
        {rows.map((c) => <CodeRow key={c.booking_id} code={c} zone={zoneOf(c.location_id)} />)}
      </ul>
    </section>
  )
}

function CodeRow({ code, zone }: { code: Code; zone?: string }) {
  if (code.code === null) return <li className="py-2 text-sm">{code.message}</li>
  return <LiveRow code={code} digits={code.code} zone={zone} />
}

function LiveRow({ code, digits, zone }: { code: Code; digits: string; zone?: string }) {
  const open = useMutation({ mutationFn: () => api.post('/api/v1/portal/bookings/{booking_id}/door-unlock', { path: { booking_id: code.booking_id } }) })
  const call = code.location_phone ? ` If it does not open, call ${code.location_phone}.` : ''
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-2">
      <div>
        <p className="font-mono text-2xl tracking-widest" aria-label={`Door code ${digits.split('').join(' ')}`}>{digits}</p>
        <p className="text-sm text-muted">
          Works {formatDateTime(code.valid_from_at, zone)} to {formatDateTime(code.valid_until_at, zone)}.{call}
        </p>
        <p role="status" className="text-sm">
          {open.isSuccess && 'The door is open.'}
          {open.isError && (open.error instanceof ApiError ? open.error.message : `The door did not open.${call}`)}
        </p>
      </div>
      {code.is_open_now && <Button size="sm" onClick={() => open.mutate()} loading={open.isPending}>Open the door</Button>}
    </li>
  )
}
