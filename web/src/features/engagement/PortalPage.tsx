import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input } from '../../components/Field'
import { PageHeader, Card } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { FormDialog, FormError, LocationSelect, TextArea } from '../billing/shared'
import { PORTAL_MENU_KEYS } from '../portal/PortalApp'

type Settings = Schemas['PortalSettingsOut']
type Video = Schemas['VideoOut']
const SOCIAL = [['facebook', 'Facebook'], ['instagram', 'Instagram'], ['x', 'X'], ['youtube', 'YouTube'], ['tiktok', 'TikTok'], ['linkedin', 'LinkedIn']] as const

function SettingsForm({ settings }: { settings: Settings }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    is_enabled: settings.is_enabled, is_public: settings.is_public, slug: settings.slug, welcome_text: settings.welcome_text ?? '',
    allows_online_purchases: settings.allows_online_purchases,
    allows_self_signup: settings.allows_self_signup, redirect_url: settings.redirect_url ?? '', redirect_domains: settings.redirect_domains.join(', '),
    social_links: { ...settings.social_links } as Record<string, string>,
    menu: PORTAL_MENU_KEYS.map((k) => {
      const saved = settings.menu.find((m) => m.key === k.key)
      return { key: k.key, label: saved?.label ?? '', is_visible: saved?.is_visible ?? true, builtIn: k.label }
    }),
  })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/locations/{location_id}/portal-settings', {
        path: { location_id: settings.location_id },
        body: {
          ...form,
          redirect_url: form.redirect_url.trim() || null,
          redirect_domains: form.redirect_domains.split(',').map((d) => d.trim()).filter(Boolean),
          social_links: Object.fromEntries(Object.entries(form.social_links).filter(([, url]) => url.trim())),
          menu: form.menu.map(({ key, label, is_visible }) => ({ key, label: label.trim() || null, is_visible })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'portal-settings'] })
      toast('success', 'Portal settings saved.')
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="max-w-2xl space-y-4">
      <FormError error={save.error} />
      <Checkbox label="Member portal is on for this location" checked={form.is_enabled} onChange={(e) => set({ is_enabled: e.target.checked })} />
      <Checkbox label="Show this location on the public landing page" checked={form.is_public} onChange={(e) => set({ is_public: e.target.checked })} />
      <Input label="Portal address (slug)" hint="Lower-case letters, numbers and dashes." value={form.slug} error={errors.slug} onChange={(e) => set({ slug: e.target.value })} />
      <TextArea label="Welcome text" value={form.welcome_text} error={errors.welcome_text} onChange={(v) => set({ welcome_text: v })} />
      <p className="text-sm text-muted">
        Online rentals are switched on per location in <Link to="/rentals/setup" className="text-primary underline">Rental setup</Link> (Online booking).
      </p>
      <Checkbox label="Allow online purchases" checked={form.allows_online_purchases} onChange={(e) => set({ allows_online_purchases: e.target.checked })} />
      <Checkbox label="Let people create their own account online" hint="They confirm their email before the account exists. Off by default." checked={form.allows_self_signup} onChange={(e) => set({ allows_self_signup: e.target.checked })} />
      <fieldset className="space-y-2">
        <legend className="font-semibold">Portal menu</legend>
        <p className="text-sm text-muted">Hide tabs members do not need, or rename them. Home and Profile always show.</p>
        {form.menu.map((m, i) => (
          <div key={m.key} className="grid items-end gap-2 sm:grid-cols-[10rem_1fr]">
            <Checkbox label={m.builtIn} checked={m.is_visible} onChange={(e) => set({ menu: form.menu.map((x, j) => (j === i ? { ...x, is_visible: e.target.checked } : x)) })} />
            <Input label={`Label for ${m.builtIn}`} placeholder={m.builtIn} value={m.label} onChange={(e) => set({ menu: form.menu.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
          </div>
        ))}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="font-semibold">Social links</legend>
        {SOCIAL.map(([network, name]) => (
          <Input key={network} label={name} type="url" placeholder="https://" value={form.social_links[network] ?? ''} error={errors[`social_links.${network}`]}
            onChange={(e) => set({ social_links: { ...form.social_links, [network]: e.target.value } })} />
        ))}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="font-semibold">After registration</legend>
        <Input label="Send people to this page" hint="An https address on your own domain or one listed below." type="url" placeholder="https://" value={form.redirect_url} error={errors.redirect_url} onChange={(e) => set({ redirect_url: e.target.value })} />
        <Input label="Allowed domains" hint="Separate with commas, for example club.example.com." value={form.redirect_domains} error={errors.redirect_domains} onChange={(e) => set({ redirect_domains: e.target.value })} />
      </fieldset>
      <Button type="submit" loading={save.isPending}>Save portal settings</Button>
    </form>
  )
}

function VideoDialog({ video, locationId, onClose }: { video?: Video; locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ title: video?.title ?? '', description: video?.description ?? '', url: video?.url ?? '', is_published: video?.is_published ?? false, sort_order: String(video?.sort_order ?? 0) })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () => {
      const body = { title: form.title, description: form.description || undefined, url: form.url, is_published: form.is_published, sort_order: Number(form.sort_order) }
      return video ? api.patch('/api/v1/videos/{video_id}', { path: { video_id: video.id }, body }) : api.post('/api/v1/videos', { body: { ...body, location_id: locationId } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'videos'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={video ? 'Edit video' : 'Add a video'} submitLabel={video ? 'Save changes' : 'Add video'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      <Input label="Title" required autoFocus value={form.title} error={errors.title} onChange={(e) => set({ title: e.target.value })} />
      <Input label="Link" hint="An https YouTube or Vimeo link." type="url" required value={form.url} error={errors.url} onChange={(e) => set({ url: e.target.value })} />
      <TextArea label="Description" value={form.description} error={errors.description} onChange={(v) => set({ description: v })} />
      <Input label="Sort order" type="number" min={0} max={10000} value={form.sort_order} error={errors.sort_order} onChange={(e) => set({ sort_order: e.target.value })} />
      <Checkbox label="Published in the member portal and app" checked={form.is_published} onChange={(e) => set({ is_published: e.target.checked })} />
    </FormDialog>
  )
}

function Videos({ locationId }: { locationId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState<Video | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Video | null>(null)
  const paging = useKeysetQuery(['engagement', 'videos', locationId], (cursor) => api.get('/api/v1/videos', { query: { cursor, location_id: locationId, sort: 'sort_order' } }))
  const remove = useMutation({
    mutationFn: (v: Video) => api.delete('/api/v1/videos/{video_id}', { path: { video_id: v.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'videos'] })
      toast('success', 'Video deleted.')
      setDeleting(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setDeleting(null)
    },
  })
  return (
    <section aria-labelledby="videos-h">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 id="videos-h">Videos</h2>
        <Button onClick={() => setEditing('new')}>Add a video</Button>
      </div>
      <Table
        caption="Videos"
        paging={paging}
        rowKey={(v) => v.id}
        empty={<EmptyState title="No videos yet">Add a YouTube or Vimeo link for members to watch.</EmptyState>}
        columns={[
          { header: 'Title', cell: (v) => <span className="font-medium">{v.title}</span> },
          { header: 'Link', cell: (v) => <a className="text-primary underline-offset-2 hover:underline" href={v.url} target="_blank" rel="noopener noreferrer">{v.url}</a> },
          { header: 'State', cell: (v) => (v.is_published ? <Badge tone="success">Published</Badge> : <Badge>Draft</Badge>) },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (v) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" aria-label={`Edit ${v.title}`} onClick={() => setEditing(v)}>Edit</Button>
                <Button size="sm" variant="danger" aria-label={`Delete ${v.title}`} onClick={() => setDeleting(v)}>Delete</Button>
              </div>
            ),
          },
        ]}
      />
      {editing && <VideoDialog video={editing === 'new' ? undefined : editing} locationId={locationId} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this video?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        {deleting?.title}
      </ConfirmDialog>
    </section>
  )
}

/** SSP-14: one set of terms for every portal sale and sign-up, kept as the documents portal_terms binding (plain
 * text here; a bound template is edited under Documents). Changing it makes buyers accept again. */
function PortalTerms() {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['document-bindings', 'portal_terms']
  const binding = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/document-bindings', { query: { scope_type: 'portal_terms', is_active: true } }) })
  const current = binding.data?.data[0]
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? current?.custom_text ?? ''
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/document-bindings', { body: { scope_type: 'portal_terms', scope_id: null, custom_text: shown.trim(), template_id: null, frequency: 'every_purchase', is_enforced_online: true, is_enforced_at_desk: false } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: key })
      setText(null)
      toast('success', 'Portal terms saved.')
    },
  })
  if (binding.isPending) return <LoadingState />
  if (binding.isError) return <ErrorState error={binding.error} onRetry={() => binding.refetch()} />
  if (current?.template_id) {
    return <p className="text-sm text-muted">The portal terms come from a document template. Change them in <Link to="/documents" className="text-primary underline">Documents</Link>.</p>
  }
  return (
    <form className="max-w-2xl space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <FormError error={save.error} />
      <TextArea label="Terms and conditions" hint="Shown at sign-up and before every portal purchase, for all locations. Changing the text asks buyers to accept again." value={shown} error={fieldErrors(save.error).custom_text} onChange={setText} />
      <Button type="submit" loading={save.isPending} disabled={!shown.trim() || text === null}>Save portal terms</Button>
    </form>
  )
}

export function PortalSettingsPage() {
  const me = useMe()
  const { can } = useAuth()
  const [locationId, setLocationId] = useState(me.primary_location_id ?? me.locations?.[0]?.id ?? '')
  const manageSettings = can('engagement.portal_settings.manage')
  const settings = useQuery({ queryKey: ['engagement', 'portal-settings', locationId], enabled: manageSettings && Boolean(locationId), queryFn: () => api.get('/api/v1/locations/{location_id}/portal-settings', { path: { location_id: locationId } }) })
  return (
    <>
      <PageHeader title="Portal and videos" description="What members see in the member portal and mobile app, per location." />
      <div className="mb-6 max-w-xs">
        <LocationSelect value={locationId} onChange={setLocationId} />
      </div>
      <div className="space-y-8">
        {manageSettings && (
          <Card title="Portal settings">
            {settings.isPending ? <LoadingState /> : settings.isError ? <ErrorState error={settings.error} onRetry={() => settings.refetch()} /> : <SettingsForm key={locationId} settings={settings.data} />}
          </Card>
        )}
        {can('documents.template.manage') && can('documents.document.generate') && (
          <Card title="Portal terms">
            <PortalTerms />
          </Card>
        )}
        {can('engagement.app_content.manage') && locationId && <Videos locationId={locationId} />}
      </div>
    </>
  )
}
