import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'

type Settings = Schemas['PublicScheduleSettingsOut']

/** The page a club's site frames (/schedule/public/:locationId; the proxy lets other sites frame it). */
export const embedSnippet = (locationId: string) =>
  `<iframe src="${window.location.origin}/schedule/public/${locationId}" title="Club schedule" width="100%" height="600" style="border:0" loading="lazy"></iframe>`

function SettingsForm({ settings }: { settings: Settings }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState(settings)
  const [copied, setCopied] = useState(false)
  const save = useMutation({
    mutationFn: () => api.patch('/api/v1/public-schedule-settings', { body: form }),
    onSuccess: (out) => {
      qc.setQueryData(['public-schedule-settings', out.location_id], out)
      toast('success', out.is_enabled ? 'Public schedule saved and published.' : 'Public schedule saved. It is not published.')
    },
  })
  const errors = fieldErrors(save.error)
  const snippet = embedSnippet(settings.location_id)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const copy = async () => {
    await navigator.clipboard.writeText(snippet)
    setCopied(true)
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form onSubmit={submit} className="grid content-start gap-4" noValidate aria-label="Public schedule settings">
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Checkbox label="Publish this location's schedule" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />
        <Checkbox label="Show sessions with seats left" checked={form.show_sessions} onChange={(e) => setForm({ ...form, show_sessions: e.target.checked })} />
        <Checkbox label="Show other bookings as busy times" hint="No names or titles, only when a court or room is taken." checked={form.show_busy} onChange={(e) => setForm({ ...form, show_busy: e.target.checked })} />
        <Input label="Days ahead" type="number" min={1} max={31} value={form.days_ahead} error={errors.days_ahead} hint="From 1 to 31." onChange={(e) => setForm({ ...form, days_ahead: Number(e.target.value) })} />
        <div>
          <Button type="submit" loading={save.isPending}>
            Save settings
          </Button>
        </div>
      </form>
      <div className="grid content-start gap-2">
        <label htmlFor="embed-snippet" className="text-sm font-medium">
          Embed snippet
        </label>
        <textarea id="embed-snippet" readOnly rows={4} value={snippet} aria-describedby="embed-note" className="w-full rounded border border-border bg-surface-2 p-3 font-mono text-xs text-fg" onFocus={(e) => e.currentTarget.select()} />
        <p id="embed-note" className="text-sm text-muted">
          Paste this into a page on your own website. It shows the published schedule; nothing appears until you publish it.
        </p>
        <div>
          <Button variant="secondary" onClick={() => void copy()}>
            {copied ? 'Copied' : 'Copy snippet'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function PublicSchedulePanel() {
  const me = useMe()
  const [locationId, setLocationId] = useState(me.primary_location_id ?? me.locations?.[0]?.id ?? '')
  const query = useQuery({
    queryKey: ['public-schedule-settings', locationId],
    queryFn: () => api.get('/api/v1/public-schedule-settings', { query: { location_id: locationId } }),
    enabled: !!locationId,
  })
  return (
    <section aria-labelledby="public-schedule-heading" className="grid gap-4">
      <div>
        <h2 id="public-schedule-heading" className="text-lg font-semibold">
          Public schedule
        </h2>
        <p className="text-sm text-muted">What anyone can see of a location's schedule, without signing in.</p>
      </div>
      <Select label="Location" className="max-w-sm" value={locationId} onChange={(e) => setLocationId(e.target.value)} options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
      {query.data ? (
        <SettingsForm key={locationId} settings={query.data} />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <LoadingState />
      )}
    </section>
  )
}
