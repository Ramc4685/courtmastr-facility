/** Phase 14 B2 staff screens for the public league site: options and branding with the embed snippet (LGE-17,
 * LGE-19, PLT-12), links (LGE-20), the photo gallery (LGE-21), sponsors (LGE-33) and news (MKT-18); and the
 * moderation queue for classifieds and pickup games (LGE-22, LGE-23). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { FileUpload } from '../../components/FileUpload'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDate, formatDateTime } from '../../lib/format'
import { FormDialog, TextArea } from '../billing/shared'
import { label } from './queries'
import { Alert, List } from './shared'

type SiteIn = Schemas['LeagueSiteIn']
type Post = Schemas['LeaguePostOut']
const IMAGE = { accept: ['image/jpeg', 'image/png'], maxBytes: 900_000 }
const SECTIONS: [keyof SiteIn, string][] = [
  ['shows_facility_info', 'Facility info'], ['shows_classes', 'Classes and clinics'], ['shows_news', 'News'],
  ['shows_gallery', 'Photo gallery'], ['shows_sponsors', 'Sponsors'], ['shows_links', 'Links'],
  ['shows_classifieds', 'Classifieds'], ['shows_pickup_games', 'Pickup games'],
]

function useInvalidate(key: string) {
  const qc = useQueryClient()
  return () => void qc.invalidateQueries({ queryKey: [key] })
}

function OptionsTab() {
  const toast = useToast()
  const site = useQuery({ queryKey: ['league-site'], queryFn: () => api.get('/api/v1/league-site') })
  const [f, setF] = useState<SiteIn | null>(null)
  useEffect(() => {
    if (site.data && !f) setF(site.data)
  }, [site.data, f])
  const save = useMutation({
    mutationFn: (body: SiteIn) => api.put('/api/v1/league-site', { body }),
    onSuccess: (row) => { setF(row); toast('success', 'League site saved.') },
  })
  if (site.isPending || !f) return site.isError ? <ErrorState error={site.error} onRetry={() => site.refetch()} /> : <LoadingState />
  const set = (patch: Partial<SiteIn>) => setF({ ...f, ...patch })
  const e = fieldErrors(save.error)
  const embed = `<iframe src="${window.location.origin}/leagues/public?embed=1" title="${f.title ?? 'Leagues'}" width="100%" height="800" loading="lazy"></iframe>`
  return (
    <div className="space-y-6">
      <form className="grid gap-4 sm:grid-cols-2" noValidate aria-label="League site options" onSubmit={(ev) => { ev.preventDefault(); save.mutate(f) }}>
        <Alert error={save.error} />
        <Checkbox className="sm:col-span-2" label="Publish the league site" hint="Schedules, standings and brackets of public competitions show whether or not this is on." checked={f.is_enabled ?? false} onChange={(ev) => set({ is_enabled: ev.target.checked })} />
        <Input label="Site title" value={f.title ?? ''} required error={e.title} onChange={(ev) => set({ title: ev.target.value })} />
        <Input label="Tagline" value={f.tagline ?? ''} error={e.tagline} onChange={(ev) => set({ tagline: ev.target.value || null })} />
        <Input label="Accent colour" hint="A hex colour such as #1a7f5a." value={f.accent_color ?? ''} error={e.accent_color} onChange={(ev) => set({ accent_color: ev.target.value || null })} />
        <Input label="TV board refresh (seconds)" type="number" min={15} max={600} value={String(f.board_refresh_sec ?? 60)} error={e.board_refresh_sec} onChange={(ev) => set({ board_refresh_sec: Number(ev.target.value) })} />
        <div className="sm:col-span-2"><TextArea label="About" value={f.about_text ?? ''} error={e.about_text} onChange={(v) => set({ about_text: v || null })} /></div>
        <fieldset className="sm:col-span-2">
          <legend className="mb-2 text-sm font-medium">Sections to show</legend>
          <div className="grid gap-2 sm:grid-cols-4">
            {SECTIONS.map(([key, text]) => <Checkbox key={key} label={text} checked={Boolean(f[key])} onChange={(ev) => set({ [key]: ev.target.checked })} />)}
          </div>
        </fieldset>
        <div><Button type="submit" loading={save.isPending}>Save</Button></div>
      </form>
      <Card title="Embed on your website">
        <p className="mb-2 text-sm text-muted">Paste this into a page of your own website. Add <code>&amp;sport=…</code> or <code>&amp;kind=tournament</code> to filter.</p>
        <TextArea label="Embed code" value={embed} onChange={() => undefined} />
      </Card>
    </div>
  )
}

function LinksTab() {
  const refresh = useInvalidate('league-links')
  const links = useQuery({ queryKey: ['league-links'], queryFn: () => api.get('/api/v1/league-links') })
  const [f, setF] = useState({ title: '', url: '', category: '' })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/league-links', { body: { title: f.title, url: f.url, category: f.category || null, sort_order: 0 } }),
    onSuccess: () => { refresh(); setF({ title: '', url: '', category: '' }) },
  })
  const remove = useMutation({ mutationFn: (id: string) => api.delete('/api/v1/league-links/{link_id}', { path: { link_id: id } }), onSuccess: refresh })
  const e = fieldErrors(add.error)
  return (
    <div className="space-y-4">
      {links.isPending ? <LoadingState /> : links.isError ? <ErrorState error={links.error} /> : (
        <List
          caption="Links"
          rows={links.data}
          rowKey={(l) => l.id}
          empty="No links yet"
          columns={[
            { header: 'Title', cell: (l) => l.title },
            { header: 'Address', cell: (l) => <span className="break-all">{l.url}</span> },
            { header: 'Category', cell: (l) => l.category ?? '—' },
            { header: 'Actions', cell: (l) => <Button size="sm" variant="secondary" aria-label={`Remove ${l.title}`} onClick={() => remove.mutate(l.id)}>Remove</Button> },
          ]}
        />
      )}
      <form className="grid gap-3 sm:grid-cols-4 sm:items-end" noValidate aria-label="Add a link" onSubmit={(ev) => { ev.preventDefault(); add.mutate() }}>
        <Alert error={add.error} />
        <Input label="Title" value={f.title} required error={e.title} onChange={(ev) => setF({ ...f, title: ev.target.value })} />
        <Input label="Address" type="url" value={f.url} required error={e.url} onChange={(ev) => setF({ ...f, url: ev.target.value })} />
        <Input label="Category" value={f.category} error={e.category} onChange={(ev) => setF({ ...f, category: ev.target.value })} />
        <div><Button type="submit" loading={add.isPending}>Add link</Button></div>
      </form>
    </div>
  )
}

function PhotosTab() {
  const refresh = useInvalidate('league-photos')
  const photos = useQuery({ queryKey: ['league-photos'], queryFn: () => api.get('/api/v1/league-photos') })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['LeaguePhotoUpdate'] }) => api.patch('/api/v1/league-photos/{photo_id}', { path: { photo_id: id }, body }),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: (id: string) => api.delete('/api/v1/league-photos/{photo_id}', { path: { photo_id: id } }), onSuccess: refresh })
  return (
    <div className="space-y-4">
      <FileUpload label="Add a photo" purpose="league_photo" route="/api/v1/league-photos" method="POST" {...IMAGE} onUploaded={refresh} />
      {photos.isPending ? <LoadingState /> : photos.isError ? <ErrorState error={photos.error} /> : (
        <List
          caption="Photos"
          rows={photos.data}
          rowKey={(p) => p.id}
          empty="No photos yet"
          columns={[
            { header: 'Caption', cell: (p) => <CaptionField key={p.caption ?? ''} caption={p.caption ?? ''} onSave={(caption) => update.mutate({ id: p.id, body: { caption: caption || null } })} /> },
            { header: 'Shown', cell: (p) => <Badge tone={p.is_published ? 'success' : 'neutral'}>{p.is_published ? 'Shown' : 'Hidden'}</Badge> },
            {
              header: 'Actions',
              cell: (p) => (
                <span className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => update.mutate({ id: p.id, body: { is_published: !p.is_published } })}>{p.is_published ? 'Hide' : 'Show'}</Button>
                  <Button size="sm" variant="secondary" aria-label={`Delete photo ${p.caption ?? ''}`.trim()} onClick={() => remove.mutate(p.id)}>Delete</Button>
                </span>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}

function CaptionField({ caption, onSave }: { caption: string; onSave: (caption: string) => void }) {
  const [value, setValue] = useState(caption)
  return <Input label="Caption" className="[&_label]:sr-only" value={value} onChange={(e) => setValue(e.target.value)} onBlur={() => value !== caption && onSave(value)} />
}

function SponsorsTab() {
  const refresh = useInvalidate('league-sponsors')
  const sponsors = useQuery({ queryKey: ['league-sponsors'], queryFn: () => api.get('/api/v1/league-sponsors') })
  const blank = { name: '', url: '', blurb: '', starts_on: '', ends_on: '' }
  const [f, setF] = useState(blank)
  const [logoFor, setLogoFor] = useState('')
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/league-sponsors', {
      body: { name: f.name, url: f.url || null, blurb: f.blurb || null, starts_on: f.starts_on || null, ends_on: f.ends_on || null, sort_order: 0, is_active: true },
    }),
    onSuccess: () => { refresh(); setF(blank) },
  })
  const toggle = useMutation({
    mutationFn: (s: Schemas['LeagueSponsorOut']) => api.patch('/api/v1/league-sponsors/{sponsor_id}', { path: { sponsor_id: s.id }, body: { is_active: !s.is_active } }),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: (id: string) => api.delete('/api/v1/league-sponsors/{sponsor_id}', { path: { sponsor_id: id } }), onSuccess: refresh })
  const e = fieldErrors(add.error)
  const rows = sponsors.data ?? []
  return (
    <div className="space-y-4">
      {sponsors.isPending ? <LoadingState /> : sponsors.isError ? <ErrorState error={sponsors.error} /> : (
        <List
          caption="Sponsors"
          rows={rows}
          rowKey={(s) => s.id}
          empty="No sponsors yet"
          columns={[
            { header: 'Sponsor', cell: (s) => s.name },
            { header: 'Runs', cell: (s) => `${s.starts_on ? formatDate(s.starts_on) : 'Now'} to ${s.ends_on ? formatDate(s.ends_on) : 'open'}` },
            { header: 'Logo', cell: (s) => (s.has_logo ? 'Yes' : 'No') },
            { header: 'Status', cell: (s) => <Badge tone={s.is_active ? 'success' : 'neutral'}>{s.is_active ? 'Active' : 'Paused'}</Badge> },
            {
              header: 'Actions',
              cell: (s) => (
                <span className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => toggle.mutate(s)}>{s.is_active ? 'Pause' : 'Resume'}</Button>
                  <Button size="sm" variant="secondary" aria-label={`Delete ${s.name}`} onClick={() => remove.mutate(s.id)}>Delete</Button>
                </span>
              ),
            },
          ]}
        />
      )}
      {rows.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 sm:items-end">
          <Select label="Logo for" value={logoFor} placeholder="Choose a sponsor" onChange={(ev) => setLogoFor(ev.target.value)} options={rows.map((s) => ({ value: s.id, label: s.name }))} />
          {logoFor && <FileUpload label="Logo" purpose="league_sponsor_logo" route="/api/v1/league-sponsors/{sponsor_id}/logo" path={{ sponsor_id: logoFor }} {...IMAGE} onUploaded={refresh} />}
        </div>
      )}
      <form className="grid gap-3 sm:grid-cols-3 sm:items-end" noValidate aria-label="Add a sponsor" onSubmit={(ev) => { ev.preventDefault(); add.mutate() }}>
        <Alert error={add.error} />
        <Input label="Name" value={f.name} required error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Input label="Website" type="url" value={f.url} error={e.url} onChange={(ev) => setF({ ...f, url: ev.target.value })} />
        <Input label="Blurb" value={f.blurb} error={e.blurb} onChange={(ev) => setF({ ...f, blurb: ev.target.value })} />
        <Input label="Starts" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => setF({ ...f, starts_on: ev.target.value })} />
        <Input label="Ends" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => setF({ ...f, ends_on: ev.target.value })} />
        <div><Button type="submit" loading={add.isPending}>Add sponsor</Button></div>
      </form>
    </div>
  )
}

function NewsTab() {
  const refresh = useInvalidate('league-news')
  const paging = useKeysetQuery(['league-news'], (cursor) => api.get('/api/v1/league-news', { query: { cursor, limit: 25 } }))
  const [open, setOpen] = useState(false)
  const toggle = useMutation({
    mutationFn: (n: Schemas['LeagueNewsOut']) => api.patch('/api/v1/league-news/{story_id}', { path: { story_id: n.id }, body: { published_at: n.published_at ? null : new Date().toISOString() } }),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: (id: string) => api.delete('/api/v1/league-news/{story_id}', { path: { story_id: id } }), onSuccess: refresh })
  return (
    <div className="space-y-4">
      <Button onClick={() => setOpen(true)}>Write a story</Button>
      <Table
        caption="News stories"
        paging={paging}
        rowKey={(n) => n.id}
        empty="No stories yet"
        columns={[
          { header: 'Title', cell: (n) => <>{n.title}{n.is_pinned ? ' (pinned)' : ''}</> },
          { header: 'Published', cell: (n) => (n.published_at ? formatDateTime(n.published_at) : <Badge>Draft</Badge>) },
          {
            header: 'Actions',
            cell: (n) => (
              <span className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => toggle.mutate(n)}>{n.published_at ? 'Unpublish' : 'Publish now'}</Button>
                <Button size="sm" variant="secondary" aria-label={`Delete ${n.title}`} onClick={() => remove.mutate(n.id)}>Delete</Button>
              </span>
            ),
          },
        ]}
      />
      {open && <StoryDialog onClose={() => { setOpen(false); refresh() }} />}
    </div>
  )
}

function StoryDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ title: '', summary: '', body: '', publish: true, pinned: false })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/league-news', {
      body: { title: f.title, summary: f.summary || null, body: f.body, is_pinned: f.pinned, published_at: f.publish ? new Date().toISOString() : null },
    }),
    onSuccess: onClose,
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="Write a story" submitLabel="Save story" busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose} size="lg">
      <Input label="Title" value={f.title} required error={e.title} onChange={(ev) => setF({ ...f, title: ev.target.value })} />
      <Input label="Summary" value={f.summary} error={e.summary} onChange={(ev) => setF({ ...f, summary: ev.target.value })} />
      <TextArea label="Story" value={f.body} required error={e.body} onChange={(v) => setF({ ...f, body: v })} />
      <Checkbox label="Publish now" hint="Leave unticked to keep it as a draft." checked={f.publish} onChange={(ev) => setF({ ...f, publish: ev.target.checked })} />
      <Checkbox label="Pin to the top" checked={f.pinned} onChange={(ev) => setF({ ...f, pinned: ev.target.checked })} />
    </FormDialog>
  )
}

export function LeagueSitePage() {
  const { can } = useAuth()
  const tabs = [
    { id: 'options', label: 'Options', content: <OptionsTab /> },
    { id: 'news', label: 'News', content: <NewsTab /> },
    { id: 'photos', label: 'Photos', content: <PhotosTab /> },
    { id: 'links', label: 'Links', content: <LinksTab /> },
    ...(can('leagues.sponsor.manage') ? [{ id: 'sponsors', label: 'Sponsors', content: <SponsorsTab /> }] : []),
  ]
  return (
    <>
      <PageHeader title="League site" description="The public pages for your leagues: what they show, how they look, and the news, photos and sponsors on them." />
      <p className="mb-4 text-sm"><a className="text-primary hover:underline" href="/leagues/public" target="_blank" rel="noopener noreferrer">Open the public site</a></p>
      <Tabs label="League site" tabs={tabs} />
    </>
  )
}

const POST_TONE: Record<string, Tone> = { pending: 'warning', approved: 'success', rejected: 'danger', withdrawn: 'neutral' }

export function LeaguePostsPage() {
  const refresh = useInvalidate('league-posts')
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const [rejecting, setRejecting] = useState<Post | null>(null)
  const paging = useKeysetQuery(['league-posts', status], (cursor) => api.get('/api/v1/league-posts', { query: { cursor, limit: 25, status: status || undefined } }))
  const approve = useMutation({
    mutationFn: (p: Post) => api.post('/api/v1/league-posts/{post_id}/approve', { path: { post_id: p.id } }),
    onSuccess: (p) => { refresh(); toast('success', `"${p.title}" is now on the league site.`) },
    onError: (e: Error) => toast('error', e.message),
  })
  return (
    <>
      <PageHeader title="Classifieds and pickup games" description="Members post from the portal; nothing shows on the league site until you approve it. Posts expire after 30 days." />
      <div className="mb-4 max-w-xs">
        <Select label="Status" value={status} placeholder="All" onChange={(e) => setStatus(e.target.value)} options={['pending', 'approved', 'rejected', 'withdrawn'].map((s) => ({ value: s, label: label(s) }))} />
      </div>
      <Table
        caption="League posts"
        paging={paging}
        rowKey={(p) => p.id}
        empty="Nothing to review"
        columns={[
          { header: 'Post', cell: (p) => <><p className="font-medium">{p.title}</p><p className="max-w-md whitespace-pre-line text-xs text-muted">{p.body}</p></> },
          { header: 'Kind', cell: (p) => `${label(p.kind)} · ${label(p.category)}` },
          { header: 'Posted by', cell: (p) => p.client_name },
          { header: 'Where and when', cell: (p) => `${p.location_name}${p.starts_at ? ` · ${formatDateTime(p.starts_at)}` : ''}` },
          { header: 'Status', cell: (p) => <Badge tone={POST_TONE[p.status] ?? 'neutral'}>{label(p.status)}</Badge> },
          {
            header: 'Actions',
            cell: (p) => (
              <span className="flex gap-2">
                {p.status === 'pending' && <Button size="sm" onClick={() => approve.mutate(p)} aria-label={`Approve ${p.title}`}>Approve</Button>}
                {(p.status === 'pending' || p.status === 'approved') && <Button size="sm" variant="secondary" onClick={() => setRejecting(p)} aria-label={`Reject ${p.title}`}>Reject</Button>}
              </span>
            ),
          },
        ]}
      />
      {rejecting && <RejectDialog post={rejecting} onClose={() => { setRejecting(null); refresh() }} />}
    </>
  )
}

function RejectDialog({ post, onClose }: { post: Post; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const reject = useMutation({ mutationFn: () => api.post('/api/v1/league-posts/{post_id}/reject', { path: { post_id: post.id }, body: { reason: reason || null } }), onSuccess: onClose })
  return (
    <FormDialog title={`Reject "${post.title}"`} submitLabel="Reject" danger busy={reject.isPending} error={reject.error} onSubmit={() => reject.mutate()} onClose={onClose}>
      <TextArea label="Reason" hint="The member sees this in the portal." value={reason} onChange={setReason} />
    </FormDialog>
  )
}
