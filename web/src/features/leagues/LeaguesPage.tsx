import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDate, formatDateTime, formatMoney, toMinor } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useRevenueCategories } from '../rentals/queries'
import { useResources } from '../resources/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { label, STATUS_TONE, useBrackets, useCompetition, useEntries, useGames, useSports, useStandings, type Competition, type Entry, type Game } from './queries'

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MANAGE = 'leagues.competition.manage'

function Alert({ error }: { error: Error | null }) {
  if (!error || Object.keys(fieldErrors(error)).length) return null
  return <p role="alert" className="text-danger sm:col-span-2">{error.message}</p>
}

/** A plain table for lists the API returns whole (team entries, standings, a competition's games). */
function List<T>({ caption, rows, columns, rowKey, empty }: { caption: string; rows: T[]; columns: { header: string; cell: (r: T) => ReactNode }[]; rowKey: (r: T) => string; empty: string }) {
  if (rows.length === 0) return <EmptyState title={empty} />
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>{columns.map((c) => <th key={c.header} scope="col" className="px-4 py-2.5 font-semibold">{c.header}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={rowKey(r)}>{columns.map((c) => <td key={c.header} className="px-4 py-2.5">{c.cell(r)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- the list

function NewCompetitionDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const sports = useSports()
  const categories = useRevenueCategories()
  const [f, setF] = useState({ name: '', kind: 'league', format: 'round_robin', sport_id: '', new_sport: '', starts_on: '', ends_on: '', fee: '', revenue_category_id: '', is_public: true })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const sportOptions = (sports.data?.data ?? []).filter((s) => s.is_active).map((s) => ({ value: s.id, label: s.name }))
  const save = useMutation({
    mutationFn: async () => {
      const sportId = f.sport_id || (await api.post('/api/v1/sports', { body: { name: f.new_sport, default_game_length_min: 60, is_active: true } })).id
      const fee = toMinor(f.fee)
      return api.post('/api/v1/competitions', {
        body: {
          location_id: locationId, kind: f.kind as 'league' | 'tournament', format: f.format as 'round_robin', name: f.name, sport_id: sportId,
          starts_on: f.starts_on, ends_on: f.ends_on || null, is_public: f.is_public, team_fee_minor: fee, revenue_category_id: fee ? f.revenue_category_id || null : null,
        },
      })
    },
    onSuccess: (row) => {
      void qc.invalidateQueries({ queryKey: ['competitions'] })
      void qc.invalidateQueries({ queryKey: ['sports'] })
      toast('success', `${row.name} created.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="New competition"
      description="A league plays a round robin; a tournament plays a bracket. Both start as a draft."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="competition-form" loading={save.isPending}>Create competition</Button>
        </>
      }
    >
      <form id="competition-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => { ev.preventDefault(); save.mutate() }}>
        <Alert error={save.error} />
        <Input label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Select label="Kind" value={f.kind} onChange={(ev) => set({ kind: ev.target.value, format: ev.target.value === 'league' ? 'round_robin' : 'single_elimination' })} options={[{ value: 'league', label: 'League' }, { value: 'tournament', label: 'Tournament' }]} />
        {f.kind === 'tournament' && (
          <Select label="Format" value={f.format} error={e.format} onChange={(ev) => set({ format: ev.target.value })} options={[{ value: 'single_elimination', label: 'Single elimination' }, { value: 'round_robin', label: 'Round robin' }, { value: 'pool_play', label: 'Pool play' }]} />
        )}
        {sportOptions.length > 0 ? (
          <Select label="Sport" value={f.sport_id} placeholder="Choose a sport" required error={e.sport_id} onChange={(ev) => set({ sport_id: ev.target.value })} options={sportOptions} />
        ) : (
          <Input label="Sport" value={f.new_sport} required hint="Your first sport is created with the competition." error={e.name} onChange={(ev) => set({ new_sport: ev.target.value })} />
        )}
        <Input label="Starts on" type="date" value={f.starts_on} required error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
        <Input label="Ends on" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
        <Input label="Team fee ($)" inputMode="decimal" value={f.fee} hint="Blank for no fee." error={e.team_fee_minor} onChange={(ev) => set({ fee: ev.target.value })} />
        {f.fee.trim() !== '' && (
          <Select label="Revenue category" value={f.revenue_category_id} placeholder="Choose a category" required error={e.revenue_category_id} onChange={(ev) => set({ revenue_category_id: ev.target.value })} options={(categories.data?.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.label }))} />
        )}
        <Checkbox className="sm:col-span-2" label="Show the schedule and standings publicly" checked={f.is_public} onChange={(ev) => set({ is_public: ev.target.checked })} />
      </form>
    </Dialog>
  )
}


export function LeaguesPage() {
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  const sports = useSports()
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery<Competition>(['competitions', location?.id], (cursor) =>
    api.get('/api/v1/competitions', { query: { location_id: location?.id, cursor, limit: 50 } }),
  )
  const sportName = (id: string) => sports.data?.data.find((s) => s.id === id)?.name ?? '—'
  return (
    <>
      <PageHeader
        title="Leagues & tournaments"
        description="Competitions, their teams, schedules, results and standings."
        actions={
          <>
            <LocationSelect />
            {can(MANAGE) && location && <Button onClick={() => setCreating(true)}>New competition</Button>}
          </>
        }
      />
      <Table<Competition>
        caption="Competitions"
        paging={paging}
        rowKey={(c) => c.id}
        empty={<EmptyState title="No competitions yet">Create a league or tournament to start.</EmptyState>}
        columns={[
          { header: 'Name', cell: (c) => <Link className="font-medium text-primary hover:underline" to={`/leagues/${c.id}`}>{c.name}</Link> },
          { header: 'Kind', cell: (c) => label(c.kind) },
          { header: 'Sport', cell: (c) => sportName(c.sport_id) },
          { header: 'Dates', cell: (c) => `${formatDate(c.starts_on)}${c.ends_on ? ` to ${formatDate(c.ends_on)}` : ''}` },
          { header: 'Status', cell: (c) => <Badge tone={STATUS_TONE[c.status]}>{label(c.status)}</Badge> },
        ]}
      />
      {creating && location && <NewCompetitionDialog locationId={location.id} onClose={() => setCreating(false)} />}
    </>
  )
}

// ---------------------------------------------------------------- one competition

function TeamsTab({ competition }: { competition: Competition }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const entries = useEntries(competition.id)
  const [name, setName] = useState('')
  const [payer, setPayer] = useState<ClientSummary | null>(null)
  const [billing, setBilling] = useState<Entry | null>(null)
  const refresh = () => void qc.invalidateQueries({ queryKey: ['competition', competition.id] })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/competitions/{competition_id}/teams', { path: { competition_id: competition.id }, body: { team: { name }, bill_to_client_id: payer?.id ?? null } }),
    onSuccess: (row) => {
      refresh()
      toast('success', row.invoice_id ? `${row.name} added and its fee invoiced.` : `${row.name} added.`)
      setName('')
      setPayer(null)
    },
  })
  const e = fieldErrors(add.error)
  if (entries.isPending) return <LoadingState />
  if (entries.isError) return <ErrorState error={entries.error} onRetry={() => entries.refetch()} />
  const fee = competition.team_fee_minor ?? 0
  return (
    <div className="space-y-4">
      {can('leagues.team.manage') && (
        <Card title="Add a team">
          <form className="grid gap-4 sm:grid-cols-3 sm:items-end" noValidate onSubmit={(ev) => { ev.preventDefault(); add.mutate() }}>
            <Alert error={add.error} />
            <Input label="Team name" value={name} required error={e['team/name']} onChange={(ev) => setName(ev.target.value)} />
            {fee > 0 && <ClientPicker label="Bill the team fee to" value={payer} onChange={setPayer} hint={`${formatMoney(fee)} per team; blank bills it later.`} error={e.bill_to_client_id} />}
            <Button type="submit" loading={add.isPending}>Add team</Button>
          </form>
        </Card>
      )}
      <List<Entry>
        caption="Teams"
        rows={entries.data}
        rowKey={(t) => t.id}
        empty="No teams yet"
        columns={[
          { header: 'Seed', cell: (t) => t.seed ?? '—' },
          { header: 'Team', cell: (t) => t.display_name ?? t.name },
          { header: 'Fee', cell: (t) => <Badge tone={t.fee_status === 'billed' ? 'success' : t.fee_status === 'unbilled' ? 'warning' : 'neutral'}>{label(t.fee_status)}</Badge> },
          {
            header: 'Actions',
            cell: (t) => t.fee_status === 'unbilled' && can('leagues.team.manage') ? <Button size="sm" variant="secondary" aria-label={`Bill the fee for ${t.name}`} onClick={() => setBilling(t)}>Bill fee</Button> : null,
          },
        ]}
      />
      {billing && <BillDialog entry={billing} onDone={() => { setBilling(null); refresh() }} />}
    </div>
  )
}

function BillDialog({ entry, onDone }: { entry: Entry; onDone: () => void }) {
  const toast = useToast()
  const [payer, setPayer] = useState<ClientSummary | null>(null)
  const bill = useMutation({
    mutationFn: () => api.post('/api/v1/competition-teams/{competition_team_id}/bill', { path: { competition_team_id: entry.id }, body: { bill_to_client_id: payer?.id ?? '' } }),
    onSuccess: () => {
      toast('success', `The fee for ${entry.name} is invoiced.`)
      onDone()
    },
  })
  return (
    <Dialog
      open
      onClose={onDone}
      title={`Bill the fee for ${entry.name}`}
      footer={
        <>
          <Button variant="secondary" onClick={onDone}>Cancel</Button>
          <Button onClick={() => bill.mutate()} loading={bill.isPending} disabled={!payer}>Bill fee</Button>
        </>
      }
    >
      <Alert error={bill.error} />
      <ClientPicker label="Bill to" value={payer} onChange={setPayer} required error={fieldErrors(bill.error).bill_to_client_id} />
    </Dialog>
  )
}

function GenerateDialog({ competition, onClose }: { competition: Competition; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const courts = useResources(competition.location_id)
  const [f, setF] = useState({ resource_id: '', weekday: '3', starts_at: '18:00', ends_at: '22:00', starts_on: competition.starts_on, ends_on: competition.ends_on ?? '' })
  const [run, setRun] = useState<Schemas['ScheduleRunOut'] | null>(null)
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const preview = useMutation({
    mutationFn: async () => {
      const created = await api.post('/api/v1/schedule-runs', {
        body: {
          location_id: competition.location_id, competition_ids: [competition.id], resource_ids: [f.resource_id], starts_on: f.starts_on, ends_on: f.ends_on,
          time_slots: [{ weekday: Number(f.weekday), starts_at: f.starts_at, ends_at: f.ends_at, resource_id: f.resource_id }],
          blackout_dates: [], bye_mode: 'hidden', removes_previous_games: false,
        },
      })
      return api.post('/api/v1/schedule-runs/{schedule_run_id}/generate', { path: { schedule_run_id: created.id } })
    },
    onSuccess: setRun,
  })
  const commit = useMutation({
    mutationFn: () => api.post('/api/v1/schedule-runs/{schedule_run_id}/commit', { path: { schedule_run_id: run?.id ?? '' } }),
    onSuccess: (done) => {
      void qc.invalidateQueries({ queryKey: ['competition', competition.id] })
      const stats = done.stats as { booked?: number; unschedulable_on_commit?: number } | null
      toast('success', `${stats?.booked ?? 0} games booked${stats?.unschedulable_on_commit ? `, ${stats.unschedulable_on_commit} could not be placed` : ''}.`)
      onClose()
    },
  })
  const e = fieldErrors(preview.error)
  const stats = run?.stats as { games?: number; byes?: number; unschedulable?: number } | null
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Generate the schedule"
      description="Every team meets every other once. Games fill the weekly window on the court in round order; committing books the court."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          {run ? (
            <Button onClick={() => commit.mutate()} loading={commit.isPending}>Book the games</Button>
          ) : (
            <Button type="submit" form="schedule-form" loading={preview.isPending}>Preview</Button>
          )}
        </>
      }
    >
      <form id="schedule-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => { ev.preventDefault(); preview.mutate() }}>
        <Alert error={preview.error ?? commit.error} />
        <Select label="Court" value={f.resource_id} placeholder="Choose a court" required error={e.resource_ids} onChange={(ev) => set({ resource_id: ev.target.value })} options={(courts.data?.data ?? []).filter((r) => r.kind === 'venue').map((r) => ({ value: r.id, label: r.name }))} />
        <Select label="Day of the week" value={f.weekday} onChange={(ev) => set({ weekday: ev.target.value })} options={WEEKDAYS.map((d, i) => ({ value: String(i + 1), label: d }))} />
        <Input label="From" type="time" value={f.starts_at} error={e['time_slots/0/starts_at']} onChange={(ev) => set({ starts_at: ev.target.value })} />
        <Input label="Until" type="time" value={f.ends_at} error={e['time_slots/0/ends_at']} onChange={(ev) => set({ ends_at: ev.target.value })} />
        <Input label="First date" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
        <Input label="Last date" type="date" value={f.ends_on} required error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
        {run && (
          <p role="status" className="sm:col-span-2">
            {stats?.games ?? 0} games proposed{stats?.unschedulable ? `, ${stats.unschedulable} without a free slot` : ''}.
          </p>
        )}
      </form>
    </Dialog>
  )
}

const side = (score: string) => ({ score: Number(score), participation: 'full' as const, went_to_overtime: false, bonus_points: 0 })

function ScoreDialog({ game, onClose }: { game: Game; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [home, setHome] = useState(game.home_score === null || game.home_score === undefined ? '' : String(game.home_score))
  const [away, setAway] = useState(game.away_score === null || game.away_score === undefined ? '' : String(game.away_score))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/games/{game_id}/result', { path: { game_id: game.id }, body: { home: side(home), away: side(away) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['competition', game.competition_id] })
      toast('success', 'Result saved; the standings are updated.')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Score: ${game.home_name ?? game.home_label} vs ${game.away_name ?? game.away_label}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="score-form" loading={save.isPending}>Save result</Button>
        </>
      }
    >
      <form id="score-form" className="grid grid-cols-2 gap-4" noValidate onSubmit={(ev) => { ev.preventDefault(); save.mutate() }}>
        <Alert error={save.error} />
        <Input label={`${game.home_name ?? 'Home'} score`} type="number" min={0} value={home} required onChange={(ev) => setHome(ev.target.value)} />
        <Input label={`${game.away_name ?? 'Away'} score`} type="number" min={0} value={away} required onChange={(ev) => setAway(ev.target.value)} />
      </form>
    </Dialog>
  )
}

function ScheduleTab({ competition }: { competition: Competition }) {
  const { can } = useAuth()
  const games = useGames(competition.id)
  const [generating, setGenerating] = useState(false)
  const [scoring, setScoring] = useState<Game | null>(null)
  if (games.isPending) return <LoadingState />
  if (games.isError) return <ErrorState error={games.error} onRetry={() => games.refetch()} />
  const rows = [...games.data.data].filter((g) => !g.is_bye).sort((a, b) => (a.starts_at ?? '~').localeCompare(b.starts_at ?? '~'))
  return (
    <div className="space-y-4">
      {can('leagues.schedule.generate') && competition.format !== 'single_elimination' && (
        <Button onClick={() => setGenerating(true)} disabled={competition.status !== 'active'}>Generate schedule</Button>
      )}
      <List<Game>
        caption="Games"
        rows={rows}
        rowKey={(g) => g.id}
        empty="No games yet"
        columns={[
          { header: 'When', cell: (g) => formatDateTime(g.starts_at) },
          { header: 'Game', cell: (g) => `${g.home_name ?? g.home_label ?? 'TBD'} vs ${g.away_name ?? g.away_label ?? 'TBD'}` },
          { header: 'Score', cell: (g) => (g.status === 'played' ? `${g.home_score} - ${g.away_score}` : '—') },
          { header: 'Status', cell: (g) => <Badge tone={STATUS_TONE[g.status]}>{label(g.status)}</Badge> },
          {
            header: 'Actions',
            cell: (g) => (['scheduled', 'played'].includes(g.status) && g.home_team_id && g.away_team_id && can('leagues.result.enter') ? (
              <Button size="sm" variant="secondary" aria-label={`Enter the score of ${g.home_name} vs ${g.away_name}`} onClick={() => setScoring(g)}>Score</Button>
            ) : null),
          },
        ]}
      />
      {generating && <GenerateDialog competition={competition} onClose={() => setGenerating(false)} />}
      {scoring && <ScoreDialog game={scoring} onClose={() => setScoring(null)} />}
    </div>
  )
}

function StandingsTab({ competitionId }: { competitionId: string }) {
  const standings = useStandings(competitionId)
  if (standings.isPending) return <LoadingState />
  if (standings.isError) return <ErrorState error={standings.error} onRetry={() => standings.refetch()} />
  return (
    <List<Schemas['LeagueStandingOut']>
      caption="Standings"
      rows={standings.data}
      rowKey={(s) => s.id}
      empty="No standings yet"
      columns={[
        { header: 'Rank', cell: (s) => s.rank },
        { header: 'Team', cell: (s) => s.team_name },
        { header: 'GP', cell: (s) => s.games_played },
        { header: 'W', cell: (s) => s.wins },
        { header: 'L', cell: (s) => s.losses },
        { header: 'T', cell: (s) => s.ties },
        { header: 'GD', cell: (s) => s.goal_difference },
        { header: 'PTS', cell: (s) => Number(s.points) },
      ]}
    />
  )
}

function BracketTab({ competition }: { competition: Competition }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const brackets = useBrackets(competition.id)
  const entries = useEntries(competition.id)
  const refresh = () => void qc.invalidateQueries({ queryKey: ['competition', competition.id] })
  const generate = useMutation({
    mutationFn: () => api.post('/api/v1/competitions/{competition_id}/brackets', { path: { competition_id: competition.id }, body: { name: 'Playoffs', has_third_place_game: false, bracket_type: 'single_elimination', seed_source: competition.format === 'single_elimination' ? 'seeds' : 'standings' } }),
    onSuccess: () => { refresh(); toast('success', 'Bracket drawn.') },
  })
  const publish = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/brackets/{bracket_id}/publish', { path: { bracket_id: id } }),
    onSuccess: () => { refresh(); toast('success', 'Bracket published; its games are on the schedule.') },
  })
  if (brackets.isPending || entries.isPending) return <LoadingState />
  if (brackets.isError) return <ErrorState error={brackets.error} onRetry={() => brackets.refetch()} />
  const name = (id: string | null | undefined) => (id ? entries.data?.find((t) => t.id === id)?.name ?? '—' : 'TBD')
  const bracket = brackets.data[0]
  if (!bracket) {
    return (
      <EmptyState title="No bracket yet" action={can('leagues.schedule.generate') ? <Button onClick={() => generate.mutate()} loading={generate.isPending}>Draw a bracket</Button> : undefined}>
        {generate.error ? <span role="alert" className="text-danger">{generate.error.message}</span> : 'Single elimination, seeded; the top seeds get the byes.'}
      </EmptyState>
    )
  }
  const rounds = [...new Set(bracket.slots.map((s) => s.round_name))]
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Badge tone={bracket.status === 'draft' ? 'neutral' : 'success'}>{label(bracket.status)}</Badge>
        {bracket.status === 'draft' && can('leagues.schedule.generate') && <Button onClick={() => publish.mutate(bracket.id)} loading={publish.isPending}>Publish bracket</Button>}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {rounds.map((round) => (
          <Card key={round} title={round}>
            <ul className="space-y-2">
              {bracket.slots.filter((s) => s.round_name === round).map((s) => (
                <li key={s.id} className="rounded border border-border px-3 py-2 text-sm">
                  {s.is_bye ? `${name(s.home_team_id)} (bye)` : `${name(s.home_team_id)} vs ${name(s.away_team_id)}`}
                  {s.winner_competition_team_id && <span className="block text-xs text-muted">Winner: {name(s.winner_competition_team_id)}</span>}
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  )
}

export function LeaguePage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const competition = useCompetition(id)
  const move = useMutation({
    mutationFn: (verb: 'activate' | 'complete' | 'reopen') => api.post(`/api/v1/competitions/{competition_id}/${verb}` as '/api/v1/competitions/{competition_id}/activate', { path: { competition_id: id } }),
    onSuccess: (row) => { void qc.invalidateQueries({ queryKey: ['competition', id] }); toast('success', `${row.name} is ${row.status}.`) },
  })
  if (competition.isPending) return <LoadingState />
  if (competition.isError) return <ErrorState error={competition.error} onRetry={() => competition.refetch()} />
  const c = competition.data
  const verb = ({ draft: 'activate', active: 'complete', completed: 'reopen' } as const)[c.status as 'draft' | 'active' | 'completed']
  return (
    <>
      <PageHeader
        title={c.name}
        description={<><Badge tone={STATUS_TONE[c.status]}>{label(c.status)}</Badge> {label(c.kind)} · {formatDate(c.starts_on)}{c.ends_on ? ` to ${formatDate(c.ends_on)}` : ''}</>}
        actions={verb && can(MANAGE) ? <Button variant="secondary" onClick={() => move.mutate(verb)} loading={move.isPending}>{label(verb)}</Button> : undefined}
      />
      {move.error && <p role="alert" className="mb-4 text-danger">{move.error.message}</p>}
      <Tabs
        label="Competition"
        tabs={[
          { id: 'teams', label: 'Teams', content: <TeamsTab competition={c} /> },
          { id: 'schedule', label: 'Schedule & results', content: <ScheduleTab competition={c} /> },
          { id: 'standings', label: 'Standings', content: <StandingsTab competitionId={c.id} /> },
          { id: 'bracket', label: 'Bracket', content: <BracketTab competition={c} /> },
        ]}
      />
    </>
  )
}
