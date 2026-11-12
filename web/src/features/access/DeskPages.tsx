import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { code128 } from './code128'
import { CARD_FIELD_LABEL, type CardField, type IdCardTemplate } from './queries'

const fail = (toast: ReturnType<typeof useToast>) => (e: unknown) => toast('error', e instanceof ApiError ? e.message : 'Saving failed.')

/** Who is in the building now, by station (CHK-07). Refreshes every 30 seconds; visits end at local midnight. */
export function OccupancyPage() {
  const { location } = useWorkingLocation()
  const locationId = location?.id ?? ''
  const room = useQuery({
    queryKey: ['occupancy', locationId],
    queryFn: () => api.get('/api/v1/occupancy', { query: { location_id: locationId } }),
    enabled: Boolean(locationId),
    refetchInterval: 30_000,
  })
  return (
    <>
      <PageHeader title="Who is in" description="Clients checked in today and not yet checked out." actions={<LocationSelect />} />
      {room.isError ? <ErrorState error={room.error} /> : !room.data ? <LoadingState /> : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
          <Card title="Count">
            <p className="text-4xl font-semibold" aria-live="polite">{room.data.count}</p>
            <ul className="mt-3 space-y-1 text-sm" aria-label="By station">
              {room.data.by_station.map((s) => (
                <li key={s.check_in_station_id ?? 'none'} className="flex justify-between gap-2">
                  <span>{s.station_name ?? 'No station'}</span>
                  <span>{s.count}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="In the building">
            {room.data.is_capped && <p className="mb-2 text-sm text-muted" role="status">Showing the latest {room.data.present.length} of {room.data.count}.</p>}
            {room.data.present.length === 0 ? <p className="text-muted">Nobody is checked in right now.</p> : (
              <table className="w-full text-sm">
                <caption className="sr-only">Clients in the building</caption>
                <thead>
                  <tr className="text-left text-muted"><th scope="col" className="py-1">Client</th><th scope="col">Since</th><th scope="col">Station</th></tr>
                </thead>
                <tbody>
                  {room.data.present.map((p) => (
                    <tr key={p.check_in_id} className="border-t border-border">
                      <td className="py-1.5"><Link to={`/clients/${p.client_id}`}>{p.client_name}</Link></td>
                      <td>{formatDateTime(p.checked_in_at, location?.time_zone)}</td>
                      <td>{p.station_name ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </>
  )
}

/** Check-in stations per location and member card layouts (CHK-07, CHK-12). */
export function DeskSetupPage() {
  const { location } = useWorkingLocation()
  const { can } = useAuth()
  const locationId = location?.id ?? ''
  return (
    <>
      <PageHeader title="Stations and member cards" description="Where clients check in, and what the printed member card shows." actions={<LocationSelect />} />
      {locationId && (
        <div className="grid gap-6 xl:grid-cols-2">
          <StationsCard key={locationId} locationId={locationId} canSave={can('access.settings.manage')} />
          <CardTemplatesCard locationId={locationId} canSave={can('access.settings.manage')} />
        </div>
      )}
    </>
  )
}

function StationsCard({ locationId, canSave }: { locationId: string; canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const stations = useQuery({ queryKey: ['check-in-stations', locationId], queryFn: () => api.get('/api/v1/check-in-stations', { query: { location_id: locationId } }) })
  const done = () => qc.invalidateQueries({ queryKey: ['check-in-stations', locationId] })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/check-in-stations', { body: { location_id: locationId, name: name.trim(), is_active: true } }),
    onSuccess: () => { setName(''); done(); toast('success', 'Station added.') },
    onError: fail(toast),
  })
  const toggle = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.patch('/api/v1/check-in-stations/{check_in_station_id}', { path: { check_in_station_id: id }, body: { is_active } }),
    onSuccess: done,
    onError: fail(toast),
  })
  return (
    <Card title="Check-in stations">
      {stations.isError ? <ErrorState error={stations.error} /> : !stations.data ? <LoadingState /> : (
        <ul className="mb-4 space-y-2" aria-label="Stations">
          {stations.data.data.length === 0 && <li className="text-muted">No stations. Check-ins here record none.</li>}
          {stations.data.data.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 rounded border border-border px-3 py-2">
              <span>{s.name} {!s.is_active && <Badge tone="neutral">Inactive</Badge>}</span>
              {canSave && (
                <Button size="sm" variant="secondary" aria-label={`${s.is_active ? 'Deactivate' : 'Activate'} ${s.name}`} onClick={() => toggle.mutate({ id: s.id, is_active: !s.is_active })}>
                  {s.is_active ? 'Deactivate' : 'Activate'}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canSave && (
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
          <Input className="flex-1" label="New station name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={!name.trim()} loading={add.isPending}>Add station</Button>
        </form>
      )}
    </Card>
  )
}

const FIELDS = Object.keys(CARD_FIELD_LABEL) as CardField[]
type TemplateForm = { id?: string; name: string; scope: 'location' | 'all'; shown_fields: CardField[]; has_photo: boolean; is_default: boolean }
const blank = (): TemplateForm => ({ name: '', scope: 'location', shown_fields: ['name', 'membership_number'], has_photo: true, is_default: false })

function CardTemplatesCard({ locationId, canSave }: { locationId: string; canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [form, setForm] = useState(blank)
  const templates = useQuery({ queryKey: ['id-card-templates'], queryFn: () => api.get('/api/v1/id-card-templates') })
  const save = useMutation({
    mutationFn: ({ id, scope, ...body }: TemplateForm) =>
      id
        ? api.patch('/api/v1/id-card-templates/{id_card_template_id}', { path: { id_card_template_id: id }, body })
        : api.post('/api/v1/id-card-templates', { body: { ...body, location_id: scope === 'all' ? null : locationId } }),
    onSuccess: () => { setForm(blank()); qc.invalidateQueries({ queryKey: ['id-card-templates'] }); toast('success', 'Card layout saved.') },
    onError: fail(toast),
  })
  const shown = (rows: IdCardTemplate[]) => rows.filter((t) => t.location_id === null || t.location_id === locationId)
  return (
    <Card title="Member card layouts">
      {templates.isError ? <ErrorState error={templates.error} /> : !templates.data ? <LoadingState /> : (
        <ul className="mb-4 space-y-2" aria-label="Card layouts">
          {shown(templates.data.data).length === 0 && <li className="text-muted">No layouts. Cards show the name and the member number.</li>}
          {shown(templates.data.data).map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border px-3 py-2">
              <div>
                <span className="font-medium">{t.name}</span> {t.is_default && <Badge tone="success">Default</Badge>}{' '}
                {t.location_id === null && <Badge tone="neutral">All locations</Badge>}
                <p className="text-xs text-muted">{t.shown_fields.map((f) => CARD_FIELD_LABEL[f]).join(', ')}{t.has_photo ? ', photo' : ''}</p>
              </div>
              {canSave && (
                <Button size="sm" variant="secondary" aria-label={`Edit ${t.name}`}
                  onClick={() => setForm({ id: t.id ?? undefined, name: t.name, scope: t.location_id ? 'location' : 'all', shown_fields: t.shown_fields, has_photo: t.has_photo, is_default: t.is_default })}>
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canSave && (
        <form className="space-y-3 border-t border-border pt-4" onSubmit={(e) => { e.preventDefault(); save.mutate(form) }}>
          <h3 className="text-sm font-semibold">{form.id ? 'Edit layout' : 'New layout'}</h3>
          <Input label="Layout name" value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          {!form.id && (
            <Select label="Used at" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value as TemplateForm['scope'] })}
              options={[{ value: 'location', label: 'This location' }, { value: 'all', label: 'Every location' }]} />
          )}
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Fields on the card</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {FIELDS.map((f) => (
                <Checkbox key={f} label={CARD_FIELD_LABEL[f]} checked={form.shown_fields.includes(f)}
                  onChange={(e) => setForm({ ...form, shown_fields: e.target.checked ? [...form.shown_fields, f] : form.shown_fields.filter((x) => x !== f) })} />
              ))}
            </div>
          </fieldset>
          <Checkbox label="Photo slot" checked={form.has_photo} onChange={(e) => setForm({ ...form, has_photo: e.target.checked })} />
          <Checkbox label="Default layout" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          <div className="flex gap-2">
            <Button type="submit" loading={save.isPending} disabled={!form.name.trim() || form.shown_fields.length === 0}>Save layout</Button>
            {form.id && <Button type="button" variant="ghost" onClick={() => setForm(blank())}>Cancel</Button>}
          </div>
        </form>
      )}
    </Card>
  )
}

/** The barcode as an SVG: one rect per bar, in the text colour, so it prints with the card. */
function Barcode({ value }: { value: string }) {
  const widths = code128(value)
  if (!widths) return <p className="text-sm text-danger">This number cannot be printed as a barcode.</p>
  const quiet = 10
  const total = widths.reduce((a, b) => a + b, 0) + quiet * 2
  let x = quiet
  const bars = widths.map((w, i) => {
    const bar = i % 2 === 0 ? <rect key={i} x={x} y={0} width={w} height={40} /> : null
    x += w
    return bar
  })
  return (
    <svg role="img" aria-label={`Barcode ${value}`} viewBox={`0 0 ${total} 40`} preserveAspectRatio="none" className="h-14 w-full fill-current text-fg">
      {bars}
    </svg>
  )
}

/** The printable member card (MEM-19). The photo slot is a placeholder until client photos exist (chip F). */
export function MemberCardPage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const { location } = useWorkingLocation()
  const locationId = params.get('location_id') ?? location?.id
  const [templateId, setTemplateId] = useState('')
  const templates = useQuery({ queryKey: ['id-card-templates'], queryFn: () => api.get('/api/v1/id-card-templates') })
  const card = useQuery({
    queryKey: ['id-card', id, locationId, templateId],
    queryFn: () => api.get('/api/v1/clients/{client_id}/id-card', {
      path: { client_id: id }, query: { location_id: locationId ?? undefined, id_card_template_id: templateId || undefined },
    }),
  })
  const c = card.data
  const name = c?.fields.find((f) => f.field === 'name')?.value
  return (
    <>
      {/* Print dark on white in any theme: the light theme's tokens (index.css :root), with a selector that
          outranks the dark ones. */}
      <style>{`@media print {
        html:root, html:root[data-theme] { color-scheme: light; --bg: 246 247 245; --surface: 255 255 255; --surface-2: 239 242 239; --border: 214 221 216; --fg: 16 24 21; --muted: 78 90 86 }
        body * { visibility: hidden } #member-card, #member-card * { visibility: visible } #member-card { position: absolute; left: 0; top: 0 }
      }`}</style>
      <PageHeader title="Member card" description="Print on a card printer or cut out along the border." actions={
        <div className="flex flex-wrap items-end gap-2">
          {(templates.data?.data.length ?? 0) > 0 && (
            <Select label="Layout" value={templateId} onChange={(e) => setTemplateId(e.target.value)}
              options={[{ value: '', label: 'Default' }, ...(templates.data?.data ?? []).map((t) => ({ value: t.id ?? '', label: t.name }))]} />
          )}
          <Button onClick={() => window.print()} disabled={!c}>Print card</Button>
        </div>
      } />
      {card.isError ? <ErrorState error={card.error} /> : !c ? <LoadingState /> : (
        <div id="member-card" className="w-[85.6mm] rounded-lg border border-border bg-surface p-4 text-fg" aria-label={`Member card for ${name ?? 'client'}`} role="region">
          <div className="flex gap-3">
            {c.template.has_photo && (
              <div className="flex h-24 w-20 shrink-0 items-center justify-center rounded border border-dashed border-border text-xs text-muted">
                {c.photo_url ? <img src={c.photo_url} alt="" className="h-full w-full object-cover" /> : 'Photo'}
              </div>
            )}
            <dl className="min-w-0 space-y-1 text-sm">
              {c.fields.map((f) => (
                <div key={f.field}>
                  <dt className="text-xs text-muted">{CARD_FIELD_LABEL[f.field]}</dt>
                  <dd className={f.field === 'name' ? 'text-base font-semibold' : ''}>{f.value ?? '—'}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="mt-3">
            {c.code_value ? <><Barcode value={c.code_value} /><p className="text-center font-mono text-xs">{c.code_value}</p></> : (
              <p className="text-sm text-muted">No member number or barcode yet: assign one on the client's profile.</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}
