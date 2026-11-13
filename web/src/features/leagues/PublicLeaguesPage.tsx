/** The anonymous league site (LGE-14, LGE-17 to LGE-24, LGE-33, MKT-18, CLS-07, PLT-12): public competitions
 * with filters kept in the URL, schedules, standings, teams, brackets and player stats, plus the site's own
 * sections (facility info, news, classes, gallery, sponsors, links, classifieds, pickup games) as the club turns
 * them on. `?embed=1` drops the page chrome for an iframe on the club's own website. No staff fields. */
import { useQuery } from '@tanstack/react-query'
import type { CSSProperties, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatDateTime } from '../../lib/format'
import { label } from './queries'
import { List } from './shared'

type Site = Schemas['PublicLeagueSiteOut']
const KINDS = ['league', 'tournament', 'ladder']
const STATUSES = ['active', 'completed']

/** The site options, or null while the club has not switched the site on (the API answers 404). */
export function usePublicSite() {
  return useQuery({
    queryKey: ['public', 'league-site'],
    queryFn: async () => {
      try {
        return await api.get('/api/v1/public/league-site')
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
}

export function PublicLeaguesPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const embed = params.get('embed') === '1'
  const site = usePublicSite()
  const options = site.data ?? null
  // The club's accent colour is tenant data, so it travels as a CSS variable the page's classes read.
  const style = options?.accent_color ? ({ '--league-accent': options.accent_color } as CSSProperties) : undefined
  return (
    <main className={embed ? 'px-2 py-2' : 'mx-auto max-w-5xl px-4 py-8'} style={style}>
      {!embed && options && <SiteBanner site={options} />}
      {id ? <PublicCompetition id={id} embed={embed} /> : <PublicList embed={embed} />}
      {!embed && !id && options && <SiteSections site={options} />}
    </main>
  )
}

function SiteBanner({ site }: { site: Site }) {
  return (
    <header className="mb-8 border-l-4 border-[var(--league-accent,rgb(var(--primary)))] pl-4">
      <p className="text-2xl font-bold">{site.title}</p>
      {site.tagline && <p className="text-muted">{site.tagline}</p>}
    </header>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-heading`} className="mt-10">
      <h2 id={`${id}-heading`} className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

/** One public list, fetched only while the club shows that section. */
function useSection<T>(name: string, on: boolean, fetch: () => Promise<T>) {
  return useQuery({ queryKey: ['public', 'league-site', name], queryFn: fetch, enabled: on })
}

function PublicList({ embed }: { embed: boolean }) {
  const [params, setParams] = useSearchParams()
  const filters = { sport_id: params.get('sport') ?? '', kind: params.get('kind') ?? '', status: params.get('status') ?? '', q: params.get('q') ?? '' }
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
  const all = useQuery({ queryKey: ['public', 'competitions'], queryFn: () => api.get('/api/v1/public/competitions') })
  const list = useQuery({ queryKey: ['public', 'competitions', query], queryFn: () => api.get('/api/v1/public/competitions', { query }) })
  const sports = [...new Map((all.data ?? []).map((c) => [c.sport_id, c.sport_name])).entries()].map(([value, name]) => ({ value, label: name }))
  const link = (id: string) => `/leagues/public/${id}${embed ? '?embed=1' : ''}`
  return (
    <>
      {!embed && <PageHeader title="Leagues & tournaments" description="Schedules, standings and results." />}
      <form role="search" aria-label="Filter competitions" className="mb-6 grid gap-3 sm:grid-cols-4" onSubmit={(e) => e.preventDefault()}>
        <Input label="Search" type="search" value={filters.q} onChange={(e) => setFilter('q', e.target.value)} />
        <Select label="Sport" value={filters.sport_id} placeholder="All sports" onChange={(e) => setFilter('sport', e.target.value)} options={sports} />
        <Select label="Type" value={filters.kind} placeholder="All types" onChange={(e) => setFilter('kind', e.target.value)} options={KINDS.map((k) => ({ value: k, label: label(k) }))} />
        <Select label="Status" value={filters.status} placeholder="Current and past" onChange={(e) => setFilter('status', e.target.value)} options={STATUSES.map((k) => ({ value: k, label: label(k) }))} />
      </form>
      {list.isPending ? <LoadingState /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> : list.data.length === 0 ? (
        <EmptyState title="No competitions match" />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {list.data.map((c) => (
            <li key={c.id}>
              <Card>
                <Link className="text-lg font-semibold text-primary hover:underline" to={link(c.id)}>{c.name}</Link>
                <p className="text-sm text-muted">
                  {c.sport_name} · {label(c.kind)} · {formatDate(c.starts_on)}{c.ends_on ? ` to ${formatDate(c.ends_on)}` : ''}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function SiteSections({ site }: { site: Site }) {
  const news = useSection('news', site.shows_news, () => api.get('/api/v1/public/league-site/news'))
  const classes = useSection('classes', site.shows_classes, () => api.get('/api/v1/public/league-site/classes'))
  const photos = useSection('photos', site.shows_gallery, () => api.get('/api/v1/public/league-site/photos'))
  const sponsors = useSection('sponsors', site.shows_sponsors, () => api.get('/api/v1/public/league-site/sponsors'))
  const links = useSection('links', site.shows_links, () => api.get('/api/v1/public/league-site/links'))
  return (
    <>
      {site.about_text && <Section id="about" title="About"><p className="whitespace-pre-line">{site.about_text}</p></Section>}
      {site.shows_news && (news.data?.length ?? 0) > 0 && (
        <Section id="news" title="News">
          <ul className="space-y-4">
            {news.data?.map((n) => (
              <li key={n.id}>
                <Card title={n.title}>
                  <p className="mb-2 text-xs text-muted">{formatDateTime(n.published_at)}{n.is_pinned ? ' · Pinned' : ''}</p>
                  <p className="whitespace-pre-line text-sm">{n.body}</p>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {site.shows_classes && (classes.data?.length ?? 0) > 0 && (
        <Section id="classes" title="Classes and clinics">
          <ul className="grid gap-4 sm:grid-cols-2">
            {classes.data?.map((c) => (
              <li key={c.id}>
                <Card title={c.name}>
                  <p className="text-sm text-muted">{label(c.kind)} · {c.location_name}{c.starts_on ? ` · from ${formatDate(c.starts_on)}` : ''}</p>
                  {c.description && <p className="mt-2 text-sm">{c.description}</p>}
                  <p className="mt-2 text-sm">
                    {c.is_open ? (c.spots_left !== null && c.spots_left !== undefined ? `${c.spots_left} spots left` : 'Open') : 'Registration closed'}
                  </p>
                  {c.is_open && <a className="mt-2 inline-block text-sm text-primary hover:underline" href="/portal/programs" target="_top">Register in the member portal</a>}
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {site.shows_classifieds && <PostsSection kind="classified" title="Classifieds" />}
      {site.shows_pickup_games && <PostsSection kind="pickup" title="Pickup games" />}
      {site.shows_gallery && (photos.data?.length ?? 0) > 0 && (
        <Section id="gallery" title="Photos">
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {photos.data?.map((p) => (
              <li key={p.id}>
                <figure>
                  <img src={`/api/v1/public/league-site/photos/${p.id}/image`} alt={p.caption ?? 'League photo'} loading="lazy" className="aspect-square w-full rounded object-cover" />
                  {p.caption && <figcaption className="mt-1 text-xs text-muted">{p.caption}</figcaption>}
                </figure>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {site.shows_sponsors && (sponsors.data?.length ?? 0) > 0 && (
        <Section id="sponsors" title="Our sponsors">
          <ul className="grid gap-4 sm:grid-cols-3">
            {sponsors.data?.map((s) => (
              <li key={s.id}>
                <Card>
                  {s.has_logo && <img src={`/api/v1/public/league-site/sponsors/${s.id}/logo`} alt="" className="mb-2 h-16 object-contain" />}
                  {s.url ? <a className="font-semibold text-primary hover:underline" href={s.url} rel="noopener noreferrer sponsored" target="_blank">{s.name}</a> : <p className="font-semibold">{s.name}</p>}
                  {s.blurb && <p className="text-sm text-muted">{s.blurb}</p>}
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {site.shows_links && (links.data?.length ?? 0) > 0 && (
        <Section id="links" title="Links">
          <ul className="space-y-1">
            {links.data?.map((l) => (
              <li key={l.url}><a className="text-primary hover:underline" href={l.url} rel="noopener noreferrer" target="_blank">{l.title}</a>{l.category ? <span className="text-sm text-muted"> · {l.category}</span> : null}</li>
            ))}
          </ul>
        </Section>
      )}
      {site.shows_facility_info && site.facilities.length > 0 && (
        <Section id="facilities" title="Our facilities">
          <ul className="grid gap-4 sm:grid-cols-2">
            {site.facilities.map((f) => (
              <li key={f.id}>
                <Card title={f.name}>
                  <p className="text-sm">{[f.city, f.region, f.postal_code].filter(Boolean).join(', ')}</p>
                  {f.phone && <p className="text-sm">Phone: <a className="text-primary hover:underline" href={`tel:${f.phone}`}>{f.phone}</a></p>}
                  {f.email && <p className="text-sm">Email: <a className="text-primary hover:underline" href={`mailto:${f.email}`}>{f.email}</a></p>}
                  <p className="mt-2 text-sm"><Link className="text-primary hover:underline" to={`/leagues/board/${f.id}`}>Today's games</Link></p>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  )
}

function PostsSection({ kind, title }: { kind: 'classified' | 'pickup'; title: string }) {
  const posts = useQuery({ queryKey: ['public', 'league-site', 'posts', kind], queryFn: () => api.get('/api/v1/public/league-site/posts', { query: { kind } }) })
  return (
    <Section id={kind} title={title}>
      {posts.isPending ? <LoadingState /> : posts.isError ? <ErrorState error={posts.error} /> : posts.data.length === 0 ? <EmptyState title="Nothing posted right now" /> : (
        <ul className="space-y-3">
          {posts.data.map((p) => (
            <li key={p.id}>
              <Card title={p.title}>
                <p className="mb-1 text-xs text-muted">
                  {label(p.category)} · {p.location_name}{p.sport_name ? ` · ${p.sport_name}` : ''}{p.starts_at ? ` · ${formatDateTime(p.starts_at)}` : ''}
                  {p.players_needed ? ` · ${p.players_needed} needed` : ''}
                </p>
                <p className="whitespace-pre-line text-sm">{p.body}</p>
              </Card>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-sm"><a className="text-primary hover:underline" href="/portal/league-posts" target="_top">Post or reply in the member portal</a></p>
    </Section>
  )
}

function PublicCompetition({ id, embed }: { id: string; embed: boolean }) {
  const path = { competition_id: id }
  const competition = useQuery({ queryKey: ['public', id], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}', { path }) })
  const games = useQuery({ queryKey: ['public', id, 'games'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/games', { path }) })
  const table = useQuery({ queryKey: ['public', id, 'standings'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/standings', { path }) })
  const teams = useQuery({ queryKey: ['public', id, 'teams'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/teams', { path }) })
  const brackets = useQuery({ queryKey: ['public', id, 'brackets'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/brackets', { path }) })
  const stats = useQuery({
    queryKey: ['public', id, 'player-stats'],
    enabled: competition.data?.show_players === true,
    queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/player-stats', { path }),
  })
  if (competition.isPending) return <LoadingState />
  if (competition.isError) return <ErrorState error={competition.error} />
  const c = competition.data
  const statKeys = [...new Set((stats.data ?? []).flatMap((s) => Object.keys(s.stats)))]
  return (
    <>
      <PageHeader title={c.name} description={`${c.sport_name} · ${formatDate(c.starts_on)}${c.ends_on ? ` to ${formatDate(c.ends_on)}` : ''}`} />
      <p className="mb-6"><Link className="text-primary hover:underline" to={`/leagues/public${embed ? '?embed=1' : ''}`}>All competitions</Link></p>
      {c.team_fee_text && <p className="mb-4">Team fee: {c.team_fee_text}</p>}
      <section aria-labelledby="standings-heading" className="mb-8">
        <h2 id="standings-heading" className="mb-3 text-lg font-semibold">Standings</h2>
        {table.isPending ? <LoadingState /> : table.isError ? <ErrorState error={table.error} /> : table.data.length === 0 ? <EmptyState title="No standings yet" /> : (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Standings</caption>
              <thead className="bg-surface-2 text-xs uppercase text-muted">
                <tr>{['Rank', 'Team', 'GP', 'W', 'L', 'T', 'GD', 'PTS'].map((h) => <th key={h} scope="col" className="px-4 py-2">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-border">
                {table.data.map((s) => (
                  <tr key={`${s.division_name}-${s.rank}-${s.team_name}`}>
                    {[s.rank, s.team_name, s.games_played, s.wins, s.losses, s.ties, s.goal_difference, Number(s.points)].map((v, i) => <td key={i} className="px-4 py-2">{v}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section aria-labelledby="schedule-heading" className="mb-8">
        <h2 id="schedule-heading" className="mb-3 text-lg font-semibold">Schedule and results</h2>
        {games.isPending ? <LoadingState /> : games.isError ? <ErrorState error={games.error} /> : games.data.length === 0 ? <EmptyState title="No games scheduled yet" /> : (
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
            {games.data.map((g) => (
              <li key={g.id} className="flex flex-wrap justify-between gap-2 px-4 py-3 text-sm">
                <span>{formatDateTime(g.starts_at)}{g.venue ? ` · ${g.venue}` : ''}</span>
                <span className="font-medium">
                  {g.home_name ?? 'TBD'} {g.status === 'played' ? `${g.home_score} - ${g.away_score}` : 'vs'} {g.away_name ?? 'TBD'}
                </span>
                {g.status === 'cancelled' && <span className="text-muted">Cancelled</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      {(brackets.data?.length ?? 0) > 0 && (
        <section aria-labelledby="brackets-heading" className="mb-8">
          <h2 id="brackets-heading" className="mb-3 text-lg font-semibold">Brackets</h2>
          {brackets.data?.map((b) => (
            <div key={b.name} className="mb-6">
              <h3 className="mb-2 font-semibold">{b.name} <Badge tone={b.status === 'completed' ? 'success' : 'info'}>{label(b.status)}</Badge></h3>
              <List
                caption={`${b.name} bracket`}
                rows={b.slots.filter((s) => !s.is_bye)}
                rowKey={(s) => `${s.side}-${s.round_no}-${s.position}`}
                empty="No games in this bracket yet"
                columns={[
                  { header: 'Round', cell: (s) => s.round_name },
                  { header: 'Home', cell: (s) => <span className={s.winner === 'home' ? 'font-semibold' : ''}>{s.home_name ?? 'TBD'}</span> },
                  { header: 'Score', cell: (s) => (s.home_score !== null && s.home_score !== undefined ? `${s.home_score} - ${s.away_score}` : '—') },
                  { header: 'Away', cell: (s) => <span className={s.winner === 'away' ? 'font-semibold' : ''}>{s.away_name ?? 'TBD'}</span> },
                  { header: 'When', cell: (s) => (s.starts_at ? formatDateTime(s.starts_at) : '—') },
                ]}
              />
            </div>
          ))}
        </section>
      )}
      <section aria-labelledby="teams-heading" className="mb-8">
        <h2 id="teams-heading" className="mb-3 text-lg font-semibold">Teams</h2>
        {teams.isPending ? <LoadingState /> : teams.isError ? <ErrorState error={teams.error} /> : teams.data.length === 0 ? <EmptyState title="No teams yet" /> : (
          <ul className="grid gap-3 sm:grid-cols-3">
            {teams.data.map((t) => (
              <li key={`${t.division_name}-${t.name}`} className="rounded-lg border border-border bg-surface p-3">
                <p className="font-semibold">{t.name}</p>
                {t.division_name && <p className="text-xs text-muted">{t.division_name}</p>}
                {t.players && t.players.length > 0 && <p className="mt-1 text-sm">{t.players.join(', ')}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
      {c.show_players && (stats.data?.length ?? 0) > 0 && (
        <section aria-labelledby="stats-heading">
          <h2 id="stats-heading" className="mb-3 text-lg font-semibold">Player stats</h2>
          <List
            caption="Player stats"
            rows={stats.data ?? []}
            rowKey={(s) => `${s.team_name}-${s.player_name}`}
            empty="No stats yet"
            columns={[
              { header: 'Player', cell: (s) => s.player_name },
              { header: 'Team', cell: (s) => s.team_name },
              ...statKeys.map((k) => ({ header: label(k), cell: (s: Schemas['PublicPlayerStatOut']) => (s.stats[k] === null || s.stats[k] === undefined ? '—' : String(s.stats[k])) })),
            ]}
          />
        </section>
      )}
    </>
  )
}

/** LGE-24: the TV board for one location. Today's public games and scores, refreshed on the club's interval,
 * no sign-in; big type for a screen across the room. */
export function LeagueBoardPage() {
  const { locationId = '' } = useParams()
  const board = useQuery({
    queryKey: ['public', 'league-board', locationId],
    queryFn: () => api.get('/api/v1/public/locations/{location_id}/league-board', { path: { location_id: locationId } }),
    refetchInterval: (q) => (q.state.data?.refresh_sec ?? 60) * 1000,
  })
  if (board.isPending) return <main className="p-8"><LoadingState /></main>
  if (board.isError) return <main className="p-8"><ErrorState error={board.error} onRetry={() => board.refetch()} /></main>
  const b = board.data
  return (
    <main className="min-h-screen bg-bg p-8">
      <header className="mb-8 flex flex-wrap items-baseline justify-between gap-4">
        <h1 className="text-4xl font-bold">{b.location_name}: today's games</h1>
        <p className="text-xl text-muted">{formatDate(b.on_date)} · updated {formatDateTime(b.generated_at, b.time_zone)}</p>
      </header>
      {b.games.length === 0 ? <EmptyState title="No games today" /> : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {b.games.map((g, i) => (
            <li key={`${g.starts_at}-${i}`} className="rounded-lg border border-border bg-surface p-6">
              <p className="text-lg text-muted">{g.starts_at ? formatDateTime(g.starts_at, b.time_zone) : 'Time to be set'}{g.venue ? ` · ${g.venue}` : ''} · {g.competition_name}</p>
              <p className="mt-2 text-3xl font-semibold">
                {g.home_name ?? 'TBD'} <span className="px-2">{g.status === 'played' ? `${g.home_score} - ${g.away_score}` : 'vs'}</span> {g.away_name ?? 'TBD'}
              </p>
              {g.status !== 'scheduled' && g.status !== 'played' && <p className="mt-1 text-lg">{label(g.status)}</p>}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
