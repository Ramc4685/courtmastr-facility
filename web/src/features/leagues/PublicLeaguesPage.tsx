import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatDateTime } from '../../lib/format'
import { label } from './queries'

/** The anonymous schedule and standings (LGE-14): public competitions only, no staff fields. */
export function PublicLeaguesPage() {
  const { id } = useParams()
  return <main className="mx-auto max-w-5xl px-4 py-8">{id ? <PublicCompetition id={id} /> : <PublicList />}</main>
}

function PublicList() {
  const list = useQuery({ queryKey: ['public', 'competitions'], queryFn: () => api.get('/api/v1/public/competitions') })
  if (list.isPending) return <LoadingState />
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />
  return (
    <>
      <PageHeader title="Leagues & tournaments" description="Schedules and standings." />
      {list.data.length === 0 ? (
        <EmptyState title="Nothing is published yet" />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {list.data.map((c) => (
            <li key={c.id}>
              <Card>
                <Link className="text-lg font-semibold text-primary hover:underline" to={`/leagues/public/${c.id}`}>{c.name}</Link>
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

function PublicCompetition({ id }: { id: string }) {
  const path = { competition_id: id }
  const competition = useQuery({ queryKey: ['public', id], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}', { path }) })
  const games = useQuery({ queryKey: ['public', id, 'games'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/games', { path }) })
  const table = useQuery({ queryKey: ['public', id, 'standings'], queryFn: () => api.get('/api/v1/public/competitions/{competition_id}/standings', { path }) })
  if (competition.isPending) return <LoadingState />
  if (competition.isError) return <ErrorState error={competition.error} />
  const c = competition.data
  return (
    <>
      <PageHeader title={c.name} description={`${c.sport_name} · ${formatDate(c.starts_on)}${c.ends_on ? ` to ${formatDate(c.ends_on)}` : ''}`} />
      <p className="mb-6"><Link className="text-primary hover:underline" to="/leagues/public">All competitions</Link></p>
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
      <section aria-labelledby="schedule-heading">
        <h2 id="schedule-heading" className="mb-3 text-lg font-semibold">Schedule</h2>
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
    </>
  )
}
