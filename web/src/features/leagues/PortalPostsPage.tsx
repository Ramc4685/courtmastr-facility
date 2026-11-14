/** Classifieds and pickup games in the member portal (LGE-22, LGE-23): post one (staff approve it before it shows),
 * see and withdraw your own, and reply to someone else's through the club's relay. Nobody's address is shown;
 * the relay mails the poster your name, email and message. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { FormDialog, TextArea } from '../billing/shared'
import { LocationPicker, usePortal } from '../portal/shared'
import { fromWallInput } from '../scheduling/time'
import { label } from './queries'

type Mine = Schemas['PortalLeaguePostOut']
type Listed = Schemas['PublicLeaguePostOut']
const TONE: Record<string, Tone> = { pending: 'warning', approved: 'success', rejected: 'danger', withdrawn: 'neutral', expired: 'neutral' }
const CATEGORIES = ['player_wanted', 'team_wanted', 'coach_wanted', 'other'] as const

function NewPost() {
  const qc = useQueryClient()
  const toast = useToast()
  const { locations, zoneOf } = usePortal()
  const blank = { kind: 'classified' as 'classified' | 'pickup', category: 'other' as (typeof CATEGORIES)[number], title: '', body: '', starts_at: '', players_needed: '', skill_level: '' }
  const [f, setF] = useState(blank)
  const [locationId, setLocationId] = useState(locations[0]?.id ?? '')
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const pickup = f.kind === 'pickup'
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/portal/league-posts', {
      body: {
        kind: f.kind, location_id: locationId, category: pickup ? 'other' : f.category, title: f.title, body: f.body,
        starts_at: pickup && f.starts_at ? fromWallInput(f.starts_at, zoneOf(locationId) ?? 'UTC') : null,
        players_needed: f.players_needed ? Number(f.players_needed) : null, skill_level: f.skill_level || null,
      },
    }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['portal', 'league-posts'] }); toast('success', 'Posted. The club checks it before it goes on the league site.'); setF(blank) },
  })
  const e = fieldErrors(create.error)
  return (
    <Card title="Post something">
      <form className="grid gap-3 sm:grid-cols-2" noValidate aria-label="New post" onSubmit={(ev) => { ev.preventDefault(); create.mutate() }}>
        {create.error && !Object.keys(e).length && <p role="alert" className="text-danger sm:col-span-2">{create.error.message}</p>}
        <Select label="Kind" value={f.kind} onChange={(ev) => set({ kind: ev.target.value as typeof f.kind })} options={[{ value: 'classified', label: 'Classified' }, { value: 'pickup', label: 'Pickup game' }]} />
        {pickup ? (
          <Input label="When" type="datetime-local" value={f.starts_at} required error={e.starts_at} onChange={(ev) => set({ starts_at: ev.target.value })} />
        ) : (
          <Select label="Category" value={f.category} onChange={(ev) => set({ category: ev.target.value as typeof f.category })} options={CATEGORIES.map((c) => ({ value: c, label: label(c) }))} />
        )}
        <LocationPicker value={locationId} onChange={setLocationId} />
        <Input label="Title" value={f.title} required error={e.title} onChange={(ev) => set({ title: ev.target.value })} />
        <Input label="Players needed" type="number" min={1} max={50} value={f.players_needed} error={e.players_needed} onChange={(ev) => set({ players_needed: ev.target.value })} />
        <Input label="Skill level" value={f.skill_level} error={e.skill_level} onChange={(ev) => set({ skill_level: ev.target.value })} />
        <div className="sm:col-span-2"><TextArea label="Details" hint="Do not include your address or phone number; replies reach you by email through the club." value={f.body} required error={e.body} onChange={(v) => set({ body: v })} /></div>
        <div><Button type="submit" loading={create.isPending}>Post</Button></div>
      </form>
    </Card>
  )
}

function MyPosts() {
  const qc = useQueryClient()
  const toast = useToast()
  const mine = useQuery({ queryKey: ['portal', 'league-posts'], queryFn: () => api.get('/api/v1/portal/league-posts') })
  const withdraw = useMutation({
    mutationFn: (p: Mine) => api.post('/api/v1/portal/league-posts/{post_id}/withdraw', { path: { post_id: p.id } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['portal', 'league-posts'] }); toast('success', 'Post withdrawn.') },
    onError: (e: Error) => toast('error', e.message),
  })
  if (mine.isPending) return <LoadingState />
  if (mine.isError) return <ErrorState error={mine.error} onRetry={() => mine.refetch()} />
  if (mine.data.length === 0) return <EmptyState title="You have not posted anything" />
  return (
    <ul className="space-y-3">
      {mine.data.map((p) => (
        <li key={p.id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-surface p-4">
          <div>
            <p className="font-medium">{p.title} <Badge tone={TONE[p.status] ?? 'neutral'}>{label(p.status)}</Badge></p>
            <p className="text-xs text-muted">{label(p.kind)} · {p.location_name} · until {formatDateTime(p.expires_at)}</p>
          </div>
          {(p.status === 'pending' || p.status === 'approved') && (
            <Button size="sm" variant="secondary" aria-label={`Withdraw ${p.title}`} onClick={() => withdraw.mutate(p)}>Withdraw</Button>
          )}
        </li>
      ))}
    </ul>
  )
}

function Board({ kind, title }: { kind: 'classified' | 'pickup'; title: string }) {
  const [replyTo, setReplyTo] = useState<Listed | null>(null)
  const posts = useQuery({ queryKey: ['portal', 'league-board', kind], queryFn: () => api.get('/api/v1/public/league-site/posts', { query: { kind } }), retry: false })
  return (
    <section aria-labelledby={`${kind}-heading`}>
      <h2 id={`${kind}-heading`} className="mb-3 text-lg font-semibold">{title}</h2>
      {posts.isPending ? <LoadingState /> : posts.isError ? <EmptyState title="The club does not list these at the moment" /> : posts.data.length === 0 ? <EmptyState title="Nothing posted right now" /> : (
        <ul className="space-y-3">
          {posts.data.map((p) => (
            <li key={p.id} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-medium">{p.title}</p>
              <p className="text-xs text-muted">
                {label(p.category)} · {p.location_name}{p.starts_at ? ` · ${formatDateTime(p.starts_at)}` : ''}{p.players_needed ? ` · ${p.players_needed} needed` : ''}
              </p>
              <p className="mt-1 whitespace-pre-line text-sm">{p.body}</p>
              <Button className="mt-2" size="sm" variant="secondary" aria-label={`Reply to ${p.title}`} onClick={() => setReplyTo(p)}>Reply</Button>
            </li>
          ))}
        </ul>
      )}
      {replyTo && <ReplyDialog post={replyTo} onClose={() => setReplyTo(null)} />}
    </section>
  )
}

function ReplyDialog({ post, onClose }: { post: Listed; onClose: () => void }) {
  const toast = useToast()
  const [message, setMessage] = useState('')
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/portal/league-posts/{post_id}/contact', { path: { post_id: post.id }, body: { message } }),
    onSuccess: () => { toast('success', 'Sent. The poster can reply to your email.'); onClose() },
  })
  return (
    <FormDialog title={`Reply to "${post.title}"`} description="We send the poster your name, email and this message." submitLabel="Send" busy={send.isPending} error={send.error} onSubmit={() => send.mutate()} onClose={onClose}>
      <TextArea label="Message" value={message} required error={fieldErrors(send.error).message} onChange={setMessage} />
    </FormDialog>
  )
}

export function PortalLeaguePostsPage() {
  return (
    <>
      <PageHeader title="Classifieds and pickup games" description="Find players, teams or a game. Posts show once the club approves them and come down after 30 days." />
      <div className="space-y-8">
        <NewPost />
        <section aria-labelledby="mine-heading">
          <h2 id="mine-heading" className="mb-3 text-lg font-semibold">My posts</h2>
          <MyPosts />
        </section>
        <Board kind="classified" title="Classifieds" />
        <Board kind="pickup" title="Pickup games" />
      </div>
    </>
  )
}
