import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { ALERT_LABEL, KIOSK_ALERTS, type KioskDevice, type KioskSettings } from './queries'

const STATUS: Record<KioskDevice['status'], { label: string; tone: 'success' | 'warning' | 'neutral' }> = {
  active: { label: 'Paired', tone: 'success' },
  pending_pairing: { label: 'Waiting to pair', tone: 'warning' },
  revoked: { label: 'Revoked', tone: 'neutral' },
}

/** Kiosk settings per location and kiosk devices (CHK-05, CHK-06). */
export function KioskSetupPage() {
  const { location } = useWorkingLocation()
  const { can } = useAuth()
  const locationId = location?.id ?? ''
  return (
    <>
      <PageHeader title="Kiosks" description="Self check-in settings and the devices that run it." actions={<LocationSelect />} />
      {locationId && (
        <div className="grid gap-6 xl:grid-cols-2">
          <SettingsCard key={locationId} locationId={locationId} canSave={can('access.settings.manage')} />
          <DevicesCard locationId={locationId} timeZone={location?.time_zone} canManage={can('access.kiosk.manage')} canLaunch={can('access.kiosk.launch')} />
        </div>
      )}
    </>
  )
}

function SettingsCard({ locationId, canSave }: { locationId: string; canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['kiosk-settings', locationId], queryFn: () => api.get('/api/v1/kiosk-settings', { query: { location_id: locationId } }) })
  const [form, setForm] = useState<KioskSettings | null>(null)
  useEffect(() => setForm(settings.data ?? null), [settings.data])
  const save = useMutation({
    mutationFn: (body: KioskSettings) =>
      api.put('/api/v1/kiosk-settings', {
        query: { location_id: locationId },
        body: {
          lookup_method: body.lookup_method as 'name' | 'membership_number' | 'both', early_window_minutes: body.early_window_minutes,
          late_window_minutes: body.late_window_minutes, welcome_message: body.welcome_message || null,
          displayed_alert_codes: body.displayed_alert_codes as never, confirmation_timeout_seconds: body.confirmation_timeout_seconds,
        },
      }),
    onSuccess: (saved) => {
      qc.setQueryData(['kiosk-settings', locationId], saved)
      toast('success', 'Kiosk settings saved.')
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Saving failed.'),
  })
  if (settings.isPending || !form) return <Card title="Settings"><LoadingState /></Card>
  if (settings.isError) return <Card title="Settings"><ErrorState error={settings.error} /></Card>
  const errors = fieldErrors(save.error)
  const set = (patch: Partial<KioskSettings>) => setForm({ ...form, ...patch })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(form)
  }
  return (
    <Card title="Settings">
      <form onSubmit={submit} className="space-y-4">
        <fieldset disabled={!canSave} className="space-y-4">
          <Select
            label="Clients find themselves by"
            value={form.lookup_method}
            onChange={(e) => set({ lookup_method: e.target.value })}
            options={[{ value: 'both', label: 'Card or last name' }, { value: 'membership_number', label: 'Card or member number only' }, { value: 'name', label: 'Last name (cards still scan)' }]}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Join a class up to (minutes before it starts)" type="number" min={0} max={1440} value={form.early_window_minutes} error={errors.early_window_minutes} onChange={(e) => set({ early_window_minutes: Number(e.target.value) })} />
            <Input label="Join a class up to (minutes after it starts)" type="number" min={0} max={1440} value={form.late_window_minutes} error={errors.late_window_minutes} onChange={(e) => set({ late_window_minutes: Number(e.target.value) })} />
          </div>
          <Input label="Welcome message" value={form.welcome_message ?? ''} maxLength={500} onChange={(e) => set({ welcome_message: e.target.value })} />
          <Input label="Return to the start screen after (seconds)" type="number" min={3} max={300} value={form.confirmation_timeout_seconds} error={errors.confirmation_timeout_seconds} onChange={(e) => set({ confirmation_timeout_seconds: Number(e.target.value) })} />
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Alerts the kiosk shows the client</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {KIOSK_ALERTS.map((code) => (
                <Checkbox
                  key={code}
                  label={ALERT_LABEL[code]}
                  checked={form.displayed_alert_codes.includes(code)}
                  onChange={(e) => set({ displayed_alert_codes: e.target.checked ? [...form.displayed_alert_codes, code] : form.displayed_alert_codes.filter((c) => c !== code) })}
                />
              ))}
            </div>
          </fieldset>
        </fieldset>
        {canSave && <Button type="submit" loading={save.isPending}>Save settings</Button>}
      </form>
    </Card>
  )
}

function DevicesCard({ locationId, timeZone, canManage, canLaunch }: { locationId: string; timeZone?: string; canManage: boolean; canLaunch: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [code, setCode] = useState<{ device: string; code: string; expires: string } | null>(null)
  const paging = useKeysetQuery(['kiosk-devices', locationId], (cursor) =>
    api.get('/api/v1/kiosk-devices', { query: { location_id: locationId, limit: 25, cursor } }),
  )
  const done = (device: string) => (out: { pairing_code: string; expires_at: string }) => {
    setCode({ device, code: out.pairing_code, expires: out.expires_at })
    qc.invalidateQueries({ queryKey: ['kiosk-devices'] })
  }
  const fail = (e: unknown) => toast('error', e instanceof ApiError ? e.message : 'That did not work.')
  const register = useMutation({
    mutationFn: () => api.post('/api/v1/kiosk-devices', { body: { location_id: locationId, name } }),
    onSuccess: (out) => {
      done(name)(out)
      setName('')
    },
    onError: fail,
  })
  const launch = useMutation({
    mutationFn: (d: KioskDevice) => api.post('/api/v1/kiosk-devices/{kiosk_device_id}/pairing-codes', { path: { kiosk_device_id: d.id } }),
    onSuccess: (out, d) => done(d.name)(out),
    onError: fail,
  })
  const revoke = useMutation({
    mutationFn: (d: KioskDevice) => api.post('/api/v1/kiosk-devices/{kiosk_device_id}/revoke', { path: { kiosk_device_id: d.id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kiosk-devices'] }),
    onError: fail,
  })
  return (
    <Card title="Devices">
      {canManage || canLaunch ? (
        <>
          {canManage && <form className="mb-4 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) register.mutate() }}>
            <Input className="flex-1" label="Device name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Front door tablet" />
            <Button type="submit" loading={register.isPending}>Register device</Button>
          </form>}
          <Table
            caption="Kiosk devices"
            paging={paging}
            rowKey={(d) => d.id}
            empty={<p className="p-6 text-muted">No kiosk devices yet.</p>}
            columns={[
              { header: 'Name', cell: (d) => d.name },
              { header: 'Status', cell: (d) => <Badge tone={STATUS[d.status].tone}>{STATUS[d.status].label}</Badge> },
              { header: 'Last seen', cell: (d) => (d.last_seen_at ? formatDateTime(d.last_seen_at, timeZone) : '—') },
              {
                header: 'Actions',
                cell: (d) =>
                  d.status === 'revoked' ? null : (
                    <div className="flex gap-2">
                      {canLaunch && <Button size="sm" variant="secondary" onClick={() => launch.mutate(d)} aria-label={`New pairing code for ${d.name}`}>Pairing code</Button>}
                      {canManage && <Button size="sm" variant="ghost" onClick={() => revoke.mutate(d)} aria-label={`Revoke ${d.name}`}>Revoke</Button>}
                    </div>
                  ),
              },
            ]}
          />
        </>
      ) : (
        <p className="text-muted">You cannot launch or register kiosks.</p>
      )}
      {code && (
        <div role="status" className="mt-4 rounded border border-border bg-surface-2 p-4">
          <p className="text-sm">Pairing code for {code.device}. Open <strong>/kiosk</strong> on the device and enter it within ten minutes:</p>
          <p className="mt-2 font-mono text-2xl tracking-widest">{code.code}</p>
          <p className="mt-1 text-xs text-muted">Expires {formatDateTime(code.expires, timeZone)}. It works once.</p>
        </div>
      )}
    </Card>
  )
}
