import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
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
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { BlankCardButton, FeeSplitDialog, PlayerStatsDialog, LadderTab, PlayerStatsTab, PreferencesDialog, PublishGroupDialog, StaffTab, usePlaces } from './depth'
import { label, STATUS_TONE, useBrackets, useCompetition, useEntries, useGames, useSports, useStandings, type Competition, type Entry, type Game } from './queries'
import { Alert, CardButton, List, matchup, ScoreDialog } from './shared'

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MANAGE = 'leagues.competition.manage'

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
          <Select label="Format" value={f.format} error={e.format} onChange={(ev) => set({ format: ev.target.value })} options={[{ value: 'single_elimination', label: 'Single elimination' }, { value: 'double_elimination', label: 'Double elimination' }, { value: 'three_games_guaranteed', label: 'Three games guaranteed' }, { value: 'round_robin', label: 'Round robin' }, { value: 'pool_play', label: 'Pool play' }]} />
        )}
        {f.kind === 'league' && (
          <Select label="Format" value={f.format} onChange={(ev) => set({ format: ev.target.value })} options={[{ value: 'round_robin', label: 'Round robin' }, { value: 'ladder', label: 'Ladder (challenges)' }]} />
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
  const [publishing, setPublishing] = useState(false)
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
            {can(MANAGE) && location && <Button variant="secondary" onClick={() => setPublishing(true)}>From a program</Button>}
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
      {publishing && location && <PublishGroupDialog locationId={location.id} onClose={() => setPublishing(false)} />}
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
  const [prefs, setPrefs] = useState<Entry | null>(null)
  const [splitting, setSplitting] = useState<Entry | null>(null)
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
            cell: (t) => (
              <div className="flex flex-wrap gap-2">
                {t.fee_status === 'unbilled' && can('leagues.team.manage') && <Button size="sm" variant="secondary" aria-label={`Bill the fee for ${t.name}`} onClick={() => setBilling(t)}>Bill fee</Button>}
                {t.fee_status === 'unbilled' && can('leagues.team.manage') && <Button size="sm" variant="secondary" aria-label={`Split the fee for ${t.name}`} onClick={() => setSplitting(t)}>Split fee</Button>}
                {can('leagues.schedule.generate') && <Button size="sm" variant="secondary" aria-label={`Scheduling preferences of ${t.name}`} onClick={() => setPrefs(t)}>Preferences</Button>}
              </div>
            ),
          },
        ]}
      />
      {billing && <BillDialog entry={billing} onDone={() => { setBilling(null); refresh() }} />}
      {prefs && <PreferencesDialog entry={prefs} competition={competition} onClose={() => setPrefs(null)} />}
      {splitting && <FeeSplitDialog entry={splitting} competition={competition} onClose={() => setSplitting(null)} />}
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

type SlotWindow = { place: string; weekday: string; starts_at: string; ends_at: string }
const NEW_WINDOW: SlotWindow = { place: '', weekday: '3', starts_at: '18:00', ends_at: '22:00' }
const BYE_MODES = [
  { value: 'hidden', label: 'Byes are not shown' },
  { value: 'occupy_slot', label: 'A bye takes a slot' },
  { value: 'fold_last_round', label: 'Fold the last round into the byes' },
  { value: 'rotate_extra_game', label: 'The team with the bye plays an extra game' },
]

function GenerateDialog({ competition, onClose }: { competition: Competition; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const places = usePlaces(competition.location_id)
  const [windows, setWindows] = useState<SlotWindow[]>([NEW_WINDOW])
  const [f, setF] = useState({ bye_mode: 'hidden', starts_on: competition.starts_on, ends_on: competition.ends_on ?? '' })
  const [runId, setRunId] = useState<string | null>(null)
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const edit = (i: number, patch: Partial<SlotWindow>) => setWindows(windows.map((w, j) => (j === i ? { ...w, ...patch } : w)))
  // The generator is a background job (LGE-08): poll the run until it leaves 'generating'.
  const run = useQuery({
    queryKey: ['schedule-run', runId],
    enabled: !!runId,
    queryFn: () => api.get('/api/v1/schedule-runs/{schedule_run_id}', { path: { schedule_run_id: runId ?? '' } }),
    refetchInterval: (q) => (q.state.data?.state === 'generating' ? 1000 : false),
  })
  const preview = useMutation({
    mutationFn: async () => {
      const slot = (w: SlotWindow) => ({ weekday: Number(w.weekday), starts_at: w.starts_at, ends_at: w.ends_at, [w.place.startsWith('v:') ? 'venue_id' : 'resource_id']: w.place.slice(2) })
      const created = await api.post('/api/v1/schedule-runs', {
        body: {
          location_id: competition.location_id, competition_ids: [competition.id], starts_on: f.starts_on, ends_on: f.ends_on,
          resource_ids: [...new Set(windows.filter((w) => w.place.startsWith('r:')).map((w) => w.place.slice(2)))],
          time_slots: windows.map(slot), blackout_dates: [], bye_mode: f.bye_mode as 'hidden', removes_previous_games: false,
        },
      })
      return api.post('/api/v1/schedule-runs/{schedule_run_id}/generate', { path: { schedule_run_id: created.id } })
    },
    onSuccess: (started) => setRunId(started.id),
  })
  const commit = useMutation({
    mutationFn: () => api.post('/api/v1/schedule-runs/{schedule_run_id}/commit', { path: { schedule_run_id: runId ?? '' } }),
    onSuccess: (done) => {
      void qc.invalidateQueries({ queryKey: ['competition', competition.id] })
      const stats = done.stats as { booked?: number; unschedulable_on_commit?: number } | null
      toast('success', `${stats?.booked ?? 0} games booked${stats?.unschedulable_on_commit ? `, ${stats.unschedulable_on_commit} could not be placed` : ''}.`)
      onClose()
    },
  })
  const e = fieldErrors(preview.error)
  const state = run.data?.state
  const stats = run.data?.stats as { games?: number; byes?: number; unschedulable?: number; predicted_completion_on?: string } | null
  const progress = run.data?.progress as { done?: number; total?: number } | null
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Generate the schedule"
      description="Every team meets every other once. Games fill the weekly windows in round order, honouring team preferences; committing books the courts."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          {state === 'previewed' ? (
            <Button onClick={() => commit.mutate()} loading={commit.isPending}>Book the games</Button>
          ) : (
            <Button type="submit" form="schedule-form" loading={preview.isPending || state === 'generating'}>Preview</Button>
          )}
        </>
      }
    >
      <form id="schedule-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => { ev.preventDefault(); setRunId(null); preview.mutate() }}>
        <Alert error={preview.error ?? commit.error} />
        <fieldset className="space-y-3 sm:col-span-2">
          <legend className="mb-1 text-sm font-medium">Weekly windows</legend>
          {windows.map((w, i) => (
            <div key={i} className="grid gap-3 rounded border border-border p-3 sm:grid-cols-5 sm:items-end">
              <Select label={`Window ${i + 1} court or venue`} value={w.place} placeholder="Choose a court" required error={e[`time_slots/${i}/resource_id`] ?? e[`time_slots/${i}/venue_id`]} onChange={(ev) => edit(i, { place: ev.target.value })} options={places} />
              <Select label={`Window ${i + 1} day`} value={w.weekday} onChange={(ev) => edit(i, { weekday: ev.target.value })} options={WEEKDAYS.map((d, n) => ({ value: String(n + 1), label: d }))} />
              <Input label={`Window ${i + 1} from`} type="time" value={w.starts_at} error={e[`time_slots/${i}/starts_at`]} onChange={(ev) => edit(i, { starts_at: ev.target.value })} />
              <Input label={`Window ${i + 1} until`} type="time" value={w.ends_at} error={e[`time_slots/${i}/ends_at`]} onChange={(ev) => edit(i, { ends_at: ev.target.value })} />
              <Button variant="secondary" aria-label={`Remove window ${i + 1}`} disabled={windows.length === 1} onClick={() => setWindows(windows.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          <Button variant="secondary" onClick={() => setWindows([...windows, { ...(windows.at(-1) ?? NEW_WINDOW), place: '' }])}>Add a window</Button>
        </fieldset>
        <Select label="Odd number of teams" value={f.bye_mode} onChange={(ev) => set({ bye_mode: ev.target.value })} options={BYE_MODES} />
        <span />
        <Input label="First date" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
        <Input label="Last date" type="date" value={f.ends_on} required error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
        {state === 'generating' && <p role="status" className="sm:col-span-2">Generating: {progress?.done ?? 0} of {progress?.total ?? 1} competitions done.</p>}
        {state === 'failed' && <p role="alert" className="text-danger sm:col-span-2">The generator failed; check the windows and preview again.</p>}
        {state === 'previewed' && (
          <p role="status" className="sm:col-span-2">
            {stats?.games ?? 0} games proposed{stats?.unschedulable ? `, ${stats.unschedulable} without a free slot` : ''}{stats?.predicted_completion_on ? `; the last game is on ${formatDate(stats.predicted_completion_on)}` : ''}.
          </p>
        )}
      </form>
    </Dialog>
  )
}

const GENERATED = ['round_robin', 'pool_play']

function ScheduleTab({ competition }: { competition: Competition }) {
  const { can } = useAuth()
  const games = useGames(competition.id)
  const [generating, setGenerating] = useState(false)
  const [scoring, setScoring] = useState<Game | null>(null)
  const [stats, setStats] = useState<Game | null>(null)
  if (games.isPending) return <LoadingState />
  if (games.isError) return <ErrorState error={games.error} onRetry={() => games.refetch()} />
  const rows = [...games.data.data].filter((g) => !g.is_bye).sort((a, b) => (a.starts_at ?? '~').localeCompare(b.starts_at ?? '~'))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        {can('leagues.schedule.generate') && GENERATED.includes(competition.format) && (
          <Button onClick={() => setGenerating(true)} disabled={competition.status !== 'active'}>Generate schedule</Button>
        )}
        {can('leagues.game_card.print') && <BlankCardButton competition={competition} />}
      </div>
      <List<Game>
        caption="Games"
        rows={rows}
        rowKey={(g) => g.id}
        empty="No games yet"
        columns={[
          { header: 'When', cell: (g) => formatDateTime(g.starts_at) },
          { header: 'Game', cell: matchup },
          { header: 'Score', cell: (g) => (g.status === 'played' ? `${g.home_score} - ${g.away_score}` : '—') },
          { header: 'Status', cell: (g) => <Badge tone={STATUS_TONE[g.status]}>{label(g.status)}</Badge> },
          {
            header: 'Actions',
            cell: (g) => (['scheduled', 'played'].includes(g.status) && g.home_team_id && g.away_team_id ? (
              <div className="flex flex-wrap gap-2">
                {can('leagues.result.enter') && <Button size="sm" variant="secondary" aria-label={`Enter the score of ${g.home_name} vs ${g.away_name}`} onClick={() => setScoring(g)}>Score</Button>}
                {can('leagues.result.enter') && <Button size="sm" variant="secondary" aria-label={`Enter player stats of ${matchup(g)}`} onClick={() => setStats(g)}>Stats</Button>}
                {can('leagues.game_card.print') && <CardButton game={g} />}
              </div>
            ) : null),
          },
        ]}
      />
      {generating && <GenerateDialog competition={competition} onClose={() => setGenerating(false)} />}
      {scoring && <ScoreDialog game={scoring} onClose={() => setScoring(null)} />}
      {stats && <PlayerStatsDialog game={stats} onClose={() => setStats(null)} />}
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
  const bracketFormat = ['double_elimination', 'three_games_guaranteed'].includes(competition.format) ? competition.format : 'single_elimination'
  const seeded = competition.format === 'pool_play' ? 'pools' : competition.format === 'round_robin' ? 'standings' : 'seeds'
  const [draw, setDraw] = useState({ bracket_type: bracketFormat, seed_source: seeded, has_reset_game: true, advance_per_pool: '2' })
  const generate = useMutation({
    mutationFn: () => api.post('/api/v1/competitions/{competition_id}/brackets', {
      path: { competition_id: competition.id },
      body: {
        name: 'Playoffs', has_third_place_game: false, bracket_type: draw.bracket_type as 'single_elimination', seed_source: draw.seed_source as 'seeds',
        has_reset_game: draw.bracket_type === 'double_elimination' && draw.has_reset_game, advance_per_pool: draw.seed_source === 'pools' ? Number(draw.advance_per_pool) : null,
      },
    }),
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
      can('leagues.schedule.generate') ? (
        <Card title="Draw a bracket">
          <div className="grid gap-4 sm:grid-cols-2 sm:items-end">
            <Select label="Bracket" value={draw.bracket_type} onChange={(ev) => setDraw({ ...draw, bracket_type: ev.target.value })} options={[{ value: 'single_elimination', label: 'Single elimination' }, { value: 'double_elimination', label: 'Double elimination' }, { value: 'three_games_guaranteed', label: 'Three games guaranteed (8 teams)' }]} />
            <Select label="Seed from" value={draw.seed_source} onChange={(ev) => setDraw({ ...draw, seed_source: ev.target.value })} options={[{ value: 'seeds', label: 'Team seeds' }, { value: 'standings', label: 'Standings' }, { value: 'pools', label: 'Pool standings (crossover)' }]} />
            {draw.bracket_type === 'double_elimination' && <Checkbox label="Play a reset game if the losers' side wins the final" checked={draw.has_reset_game} onChange={(ev) => setDraw({ ...draw, has_reset_game: ev.target.checked })} />}
            {draw.seed_source === 'pools' && <Input label="Teams advancing per pool" type="number" min={1} value={draw.advance_per_pool} onChange={(ev) => setDraw({ ...draw, advance_per_pool: ev.target.value })} />}
            <Alert error={generate.error} />
            <div><Button onClick={() => generate.mutate()} loading={generate.isPending}>Draw a bracket</Button></div>
          </div>
        </Card>
      ) : <EmptyState title="No bracket yet" />
    )
  }
  const roundTitle = (s: Schemas['BracketSlotOut']) => (s.side === 'winners' ? s.round_name : `${label(s.side)}: ${s.round_name}`)
  const rounds = [...new Set(bracket.slots.map(roundTitle))]
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
              {bracket.slots.filter((s) => roundTitle(s) === round).map((s) => (
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
          ...(c.format === 'ladder' ? [{ id: 'ladder', label: 'Ladder', content: <LadderTab competition={c} /> }] : []),
          { id: 'player-stats', label: 'Player stats', content: <PlayerStatsTab competition={c} /> },
          ...(can(MANAGE) ? [{ id: 'staff', label: 'Staff', content: <StaffTab competition={c} /> }] : []),
        ]}
      />
    </>
  )
}
