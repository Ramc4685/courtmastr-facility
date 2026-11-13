/** Phase 14 B1 league depth screens: venues (RES-06), formula stats (LGE-07), the scorekeeper screen and
 * competition staff (LGE-26), ladders (LGE-28), player stats, team preferences (LGE-10), the team fee split
 * (REG-26) and publishing a program group as a competition (REG-14). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney, toMinor } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useResources } from '../resources/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { label, STATUS_TONE, useEntries, useSports, type Competition, type Entry, type Game } from './queries'
import { Alert, CardButton, List, matchup, ScoreDialog } from './shared'

const MANAGE = 'leagues.competition.manage'
type Venue = Schemas['VenueOut']
type StatTable = Schemas['StatTableOut']
type Roster = Schemas['LeagueRosterEntryOut']

const useVenues = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['league-venues', locationId],
    enabled: !!locationId,
    queryFn: () => api.get('/api/v1/league-venues', { query: { location_id: locationId, limit: 200 } }),
  })

export const useCourts = (locationId: string | undefined) => {
  const resources = useResources(locationId ?? '')
  return (resources.data?.data ?? []).filter((r) => r.kind === 'venue')
}

/** Courts and venues as one select: "r:<id>" books one court, "v:<id>" every court of a venue. */
export function usePlaces(locationId: string | undefined) {
  const courts = useCourts(locationId)
  const venues = useVenues(locationId)
  return [
    ...courts.map((c) => ({ value: `r:${c.id}`, label: c.name })),
    ...(venues.data?.data ?? []).filter((v) => v.is_active).map((v) => ({ value: `v:${v.id}`, label: `${v.name} (venue)` })),
  ]
}

// ---------------------------------------------------------------- venues (RES-06)

export function VenuesPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { location } = useWorkingLocation()
  const courts = useCourts(location?.id)
  const venues = useVenues(location?.id)
  const [name, setName] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const refresh = () => void qc.invalidateQueries({ queryKey: ['league-venues'] })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/league-venues', { body: { location_id: location?.id ?? '', name, resource_ids: picked, is_active: true } }),
    onSuccess: (row) => { refresh(); toast('success', `${row.name} added.`); setName(''); setPicked([]) },
  })
  const remove = useMutation({
    mutationFn: (v: Venue) => api.delete('/api/v1/league-venues/{venue_id}', { path: { venue_id: v.id } }),
    onSuccess: () => { refresh(); toast('success', 'Venue removed.') },
    onError: (e: Error) => toast('error', e.message),
  })
  const e = fieldErrors(create.error)
  const courtName = (id: string) => courts.find((c) => c.id === id)?.name ?? '—'
  return (
    <>
      <PageHeader title="League venues" description="A venue groups courts that a game takes together; the schedule generator books every court of the venue." actions={<LocationSelect />} />
      {location && (
        <Card title="Add a venue">
          <form className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => { ev.preventDefault(); create.mutate() }}>
            <Alert error={create.error} />
            <Input label="Venue name" value={name} required error={e.name} onChange={(ev) => setName(ev.target.value)} />
            <fieldset className="sm:col-span-2">
              <legend className="mb-2 text-sm font-medium">Courts</legend>
              <div className="flex flex-wrap gap-4">
                {courts.map((c) => (
                  <Checkbox key={c.id} label={c.name} checked={picked.includes(c.id)} onChange={(ev) => setPicked(ev.target.checked ? [...picked, c.id] : picked.filter((id) => id !== c.id))} />
                ))}
              </div>
              {e.resource_ids && <p className="mt-1 text-sm text-danger">{e.resource_ids}</p>}
            </fieldset>
            <div><Button type="submit" loading={create.isPending} disabled={!picked.length}>Add venue</Button></div>
          </form>
        </Card>
      )}
      <div className="mt-6">
        {venues.isPending ? <LoadingState /> : venues.isError ? <ErrorState error={venues.error} onRetry={() => venues.refetch()} /> : (
          <List<Venue>
            caption="Venues"
            rows={venues.data.data}
            rowKey={(v) => v.id}
            empty="No venues yet"
            columns={[
              { header: 'Venue', cell: (v) => v.name },
              { header: 'Courts', cell: (v) => v.resource_ids.map(courtName).join(', ') },
              { header: 'Actions', cell: (v) => <Button size="sm" variant="secondary" aria-label={`Remove ${v.name}`} loading={remove.isPending && remove.variables?.id === v.id} onClick={() => remove.mutate(v)}>Remove</Button> },
            ]}
          />
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------- stats (LGE-07)

const useStatTables = (sportId: string) =>
  useQuery({
    queryKey: ['stat-tables', sportId],
    enabled: !!sportId,
    queryFn: () => api.get('/api/v1/sports/{sport_id}/stat-tables', { path: { sport_id: sportId } }),
  })

const BLANK_STAT = { code: '', name: '', kind: 'entry', formula: '', decimal_places: '0' }

function AddStatForm({ table }: { table: StatTable }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState(BLANK_STAT)
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/stat-tables/{stat_table_id}/stats', {
      path: { stat_table_id: table.id },
      body: { code: f.code, name: f.name, kind: f.kind as 'entry' | 'formula', formula: f.kind === 'formula' ? f.formula : null, decimal_places: Number(f.decimal_places), sort_order: table.stats.length },
    }),
    onSuccess: (row) => { void qc.invalidateQueries({ queryKey: ['stat-tables'] }); toast('success', `${row.name} added.`); setF(BLANK_STAT) },
  })
  const e = fieldErrors(add.error)
  return (
    <form className="mt-4 grid gap-3 sm:grid-cols-5 sm:items-end" noValidate aria-label={`Add a stat to ${table.name}`} onSubmit={(ev) => { ev.preventDefault(); add.mutate() }}>
      <Alert error={add.error} />
      <Input label="Code" value={f.code} required hint="Used in formulas" error={e.code} onChange={(ev) => set({ code: ev.target.value.toUpperCase() })} />
      <Input label="Stat name" value={f.name} required error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
      <Select label="Kind" value={f.kind} onChange={(ev) => set({ kind: ev.target.value })} options={[{ value: 'entry', label: 'Entered per game' }, { value: 'formula', label: 'Formula' }]} />
      {f.kind === 'formula' ? (
        <Input label="Formula" value={f.formula} required hint="e.g. G / GP" error={e.formula} onChange={(ev) => set({ formula: ev.target.value })} />
      ) : (
        <Input label="Decimals" type="number" min={0} max={4} value={f.decimal_places} onChange={(ev) => set({ decimal_places: ev.target.value })} />
      )}
      <Button type="submit" loading={add.isPending}>Add stat</Button>
    </form>
  )
}

export function StatsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const sports = useSports()
  const [sportId, setSportId] = useState('')
  const sport = sportId || sports.data?.data[0]?.id || ''
  const tables = useStatTables(sport)
  const [tableName, setTableName] = useState('')
  const refresh = () => void qc.invalidateQueries({ queryKey: ['stat-tables'] })
  const addTable = useMutation({
    mutationFn: () => api.post('/api/v1/sports/{sport_id}/stat-tables', { path: { sport_id: sport }, body: { name: tableName, sort_order: tables.data?.length ?? 0 } }),
    onSuccess: () => { refresh(); setTableName('') },
  })
  const removeStat = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/stat-definitions/{stat_definition_id}', { path: { stat_definition_id: id } }),
    onSuccess: () => { refresh(); toast('success', 'Stat removed.') },
    onError: (e: Error) => toast('error', e.message),
  })
  return (
    <>
      <PageHeader title="Player stats" description="Stats scorekeepers enter per player per game, and formula stats worked out from them." />
      <div className="mb-6 grid gap-4 sm:grid-cols-3 sm:items-end">
        <Select label="Sport" value={sport} onChange={(ev) => setSportId(ev.target.value)} options={(sports.data?.data ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        <form className="flex items-end gap-2 sm:col-span-2" noValidate onSubmit={(ev) => { ev.preventDefault(); addTable.mutate() }}>
          <Input label="New stat table" value={tableName} required error={fieldErrors(addTable.error).name} onChange={(ev) => setTableName(ev.target.value)} />
          <Button type="submit" variant="secondary" loading={addTable.isPending} disabled={!sport}>Add table</Button>
        </form>
      </div>
      <div className="mb-4"><Alert error={addTable.error} /></div>
      {!sport ? <EmptyState title="Add a sport first" /> : tables.isPending ? <LoadingState /> : tables.isError ? <ErrorState error={tables.error} onRetry={() => tables.refetch()} /> : tables.data.length === 0 ? <EmptyState title="No stat tables yet" /> : (
        <div className="space-y-6">
          {tables.data.map((t) => (
            <Card key={t.id} title={t.name}>
              <List<Schemas['StatDefinitionOut']>
                caption={`${t.name} stats`}
                rows={t.stats}
                rowKey={(s) => s.id}
                empty="No stats yet"
                columns={[
                  { header: 'Code', cell: (s) => s.code },
                  { header: 'Stat', cell: (s) => s.name },
                  { header: 'Kind', cell: (s) => (s.kind === 'formula' ? `Formula: ${s.formula}` : 'Entered') },
                  { header: 'Actions', cell: (s) => <Button size="sm" variant="secondary" aria-label={`Remove ${s.name}`} onClick={() => removeStat.mutate(s.id)}>Remove</Button> },
                ]}
              />
              <AddStatForm table={t} />
            </Card>
          ))}
        </div>
      )}
    </>
  )
}

/** Per player per game entry of a game's entry stats, for both rosters. */
export function PlayerStatsDialog({ game, onClose }: { game: Game; onClose: () => void }) {
  const sportId = game.sport_id ?? ''
  const toast = useToast()
  const tables = useStatTables(sportId)
  const rosters = useQuery({
    queryKey: ['game-rosters', game.id],
    queryFn: async () => (await Promise.all(
      [game.home_team_id, game.away_team_id].filter((id): id is string => !!id).map((id) => api.get('/api/v1/competition-teams/{competition_team_id}/roster', { path: { competition_team_id: id } })),
    )).flat(),
  })
  const recorded = useQuery({ queryKey: ['player-stats', game.id], queryFn: () => api.get('/api/v1/games/{game_id}/player-stats', { path: { game_id: game.id } }) })
  const [values, setValues] = useState<Record<string, string>>({})
  const entry = (tables.data ?? []).flatMap((t) => t.stats).filter((s) => s.kind === 'entry')
  const value = (r: string, s: string) => values[`${r}|${s}`] ?? String(recorded.data?.find((x) => x.roster_entry_id === r && x.stat_definition_id === s)?.value ?? '')
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/games/{game_id}/player-stats', {
      path: { game_id: game.id },
      body: { stats: (rosters.data ?? []).flatMap((r) => entry.map((s) => ({ roster_entry_id: r.id, stat_definition_id: s.id, value: value(r.id, s.id) })).filter((x) => x.value !== '')) },
    }),
    onSuccess: () => { toast('success', 'Player stats saved.'); onClose() },
  })
  const loading = tables.isPending || rosters.isPending || recorded.isPending
  return (
    <Dialog open size="lg" onClose={onClose} title={`Player stats: ${matchup(game)}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate()} loading={save.isPending} disabled={loading || !entry.length}>Save stats</Button></>}>
      <Alert error={save.error} />
      {loading ? <LoadingState /> : !entry.length ? <EmptyState title="No entered stats for this sport" /> : (
        <List<Roster>
          caption="Player stats"
          rows={rosters.data ?? []}
          rowKey={(r) => r.id}
          empty="No players on the rosters"
          columns={[
            { header: 'Player', cell: (r) => r.name },
            ...entry.map((s) => ({
              header: s.code,
              cell: (r: Roster) => <Input label={<span className="sr-only">{`${s.name} for ${r.name}`}</span>} className="w-20 [&>label]:sr-only" type="number" min={0} value={value(r.id, s.id)} onChange={(ev) => setValues({ ...values, [`${r.id}|${s.id}`]: ev.target.value })} />,
            })),
          ]}
        />
      )}
    </Dialog>
  )
}

export function PlayerStatsTab({ competition }: { competition: Competition }) {
  const totals = useQuery({ queryKey: ['competition', competition.id, 'player-stats'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/player-stats', { path: { competition_id: competition.id } }) })
  if (totals.isPending) return <LoadingState />
  if (totals.isError) return <ErrorState error={totals.error} onRetry={() => totals.refetch()} />
  const codes = [...new Set(totals.data.flatMap((t) => Object.keys(t.stats)))]
  return (
    <List<Schemas['PlayerTotalsOut']>
      caption="Player stat totals"
      rows={totals.data}
      rowKey={(t) => t.roster_entry_id}
      empty="No player stats yet"
      columns={[{ header: 'Player', cell: (t) => t.player_name }, ...codes.map((c) => ({ header: c, cell: (t: Schemas['PlayerTotalsOut']) => (t.stats[c] === null || t.stats[c] === undefined ? '—' : Number(t.stats[c])) }))]}
    />
  )
}

// ---------------------------------------------------------------- scorekeepers (LGE-26)

export function ScoresPage() {
  const [scoring, setScoring] = useState<Game | null>(null)
  const [stats, setStats] = useState<Game | null>(null)
  const paging = useKeysetQuery<Game>(['score-games'], (cursor) => api.get('/api/v1/games', { query: { sort: 'starts_at', cursor, limit: 50 } }))
  return (
    <>
      <PageHeader title="Scores" description="The games of the competitions you keep score for." />
      <Table<Game>
        caption="Games to score"
        paging={paging}
        rowKey={(g) => g.id}
        empty={<EmptyState title="No games to score">A league admin assigns you to a competition.</EmptyState>}
        columns={[
          { header: 'When', cell: (g) => formatDateTime(g.starts_at) },
          { header: 'Competition', cell: (g) => g.competition_name ?? '—' },
          { header: 'Game', cell: matchup },
          { header: 'Score', cell: (g) => (g.status === 'played' ? `${g.home_score} - ${g.away_score}` : '—') },
          { header: 'Status', cell: (g) => <Badge tone={STATUS_TONE[g.status]}>{label(g.status)}</Badge> },
          {
            header: 'Actions',
            cell: (g) => (g.home_team_id && g.away_team_id && ['scheduled', 'played'].includes(g.status) ? (
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" aria-label={`Enter the score of ${matchup(g)}`} onClick={() => setScoring(g)}>Score</Button>
                <Button size="sm" variant="secondary" aria-label={`Enter player stats of ${matchup(g)}`} onClick={() => setStats(g)}>Stats</Button>
                <CardButton game={g} />
              </div>
            ) : null),
          },
        ]}
      />
      {scoring && <ScoreDialog game={scoring} onClose={() => setScoring(null)} />}
      {stats && <PlayerStatsDialog game={stats} onClose={() => setStats(null)} />}
    </>
  )
}

const useStaffCandidates = (competitionId: string) =>
  useQuery({ queryKey: ['competition', competitionId, 'staff-candidates'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/staff-candidates', { path: { competition_id: competitionId } }) })

type StaffRow = { staff_user_id: string; role: 'league_admin' | 'scorekeeper' }

export function StaffTab({ competition }: { competition: Competition }) {
  const qc = useQueryClient()
  const toast = useToast()
  const people = useStaffCandidates(competition.id)
  const staff = useQuery({ queryKey: ['competition', competition.id, 'staff'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/staff', { path: { competition_id: competition.id } }) })
  const [who, setWho] = useState('')
  const [role, setRole] = useState<StaffRow['role']>('scorekeeper')
  const save = useMutation({
    mutationFn: (rows: StaffRow[]) => api.put('/api/v1/competitions/{competition_id}/staff', { path: { competition_id: competition.id }, body: { staff: rows } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['competition', competition.id, 'staff'] }); toast('success', 'Competition staff saved.'); setWho('') },
  })
  if (staff.isPending) return <LoadingState />
  if (staff.isError) return <ErrorState error={staff.error} onRetry={() => staff.refetch()} />
  const current: StaffRow[] = staff.data.map((s) => ({ staff_user_id: s.staff_user_id, role: s.role as StaffRow['role'] }))
  const nameOf = (id: string) => people.data?.find((u) => u.id === id)?.name ?? '—'
  return (
    <div className="space-y-4">
      <Card title="Assign staff">
        <form className="grid gap-4 sm:grid-cols-3 sm:items-end" noValidate onSubmit={(ev) => { ev.preventDefault(); save.mutate([...current.filter((s) => s.staff_user_id !== who), { staff_user_id: who, role }]) }}>
          <Alert error={save.error} />
          <Select label="Staff member" value={who} placeholder="Choose a person" required onChange={(ev) => setWho(ev.target.value)} options={(people.data ?? []).map((u) => ({ value: u.id, label: u.name }))} />
          <Select label="Role in this competition" value={role} onChange={(ev) => setRole(ev.target.value as StaffRow['role'])} options={[{ value: 'scorekeeper', label: 'Scorekeeper' }, { value: 'league_admin', label: 'League admin' }]} />
          <Button type="submit" loading={save.isPending} disabled={!who}>Assign</Button>
        </form>
        <p className="mt-3 text-sm text-muted">Scorekeepers see and score only the games of the competitions they are assigned to.</p>
      </Card>
      <List<Schemas['CompetitionStaffOut']>
        caption="Competition staff"
        rows={staff.data}
        rowKey={(s) => s.id}
        empty="No one assigned yet"
        columns={[
          { header: 'Person', cell: (s) => nameOf(s.staff_user_id) },
          { header: 'Role', cell: (s) => label(s.role) },
          { header: 'Actions', cell: (s) => <Button size="sm" variant="secondary" aria-label={`Unassign ${nameOf(s.staff_user_id)}`} onClick={() => save.mutate(current.filter((c) => c.staff_user_id !== s.staff_user_id))}>Unassign</Button> },
        ]}
      />
    </div>
  )
}

// ---------------------------------------------------------------- ladder (LGE-28)

export function LadderTab({ competition }: { competition: Competition }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const entries = useEntries(competition.id)
  const ladder = useQuery({ queryKey: ['competition', competition.id, 'ladder'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/ladder', { path: { competition_id: competition.id } }) })
  const [challenger, setChallenger] = useState('')
  const [defender, setDefender] = useState('')
  const refresh = () => void qc.invalidateQueries({ queryKey: ['competition', competition.id] })
  const order = useMutation({
    mutationFn: () => api.put('/api/v1/competitions/{competition_id}/ladder', { path: { competition_id: competition.id }, body: { competition_team_ids: (entries.data ?? []).map((t) => t.id) } }),
    onSuccess: () => { refresh(); toast('success', 'Ladder set from the team order.') },
  })
  const challenge = useMutation({
    mutationFn: () => api.post('/api/v1/competitions/{competition_id}/ladder-challenges', { path: { competition_id: competition.id }, body: { challenger_id: challenger, defender_id: defender } }),
    onSuccess: () => { refresh(); toast('success', 'Challenge added to the schedule; give it a court and time there.'); setChallenger(''); setDefender('') },
  })
  if (ladder.isPending) return <LoadingState />
  if (ladder.isError) return <ErrorState error={ladder.error} onRetry={() => ladder.refetch()} />
  const teams = ladder.data.map((r) => ({ value: r.competition_team_id, label: `${r.position}. ${r.team_name ?? ''}` }))
  return (
    <div className="space-y-4">
      {can(MANAGE) && <Button variant="secondary" onClick={() => order.mutate()} loading={order.isPending}>Set the ladder from the team order</Button>}
      <Alert error={order.error} />
      {ladder.data.length > 1 && can('leagues.game.manage') && (
        <Card title="Challenge">
          <form className="grid gap-4 sm:grid-cols-3 sm:items-end" noValidate onSubmit={(ev) => { ev.preventDefault(); challenge.mutate() }}>
            <Alert error={challenge.error} />
            <Select label="Challenger" value={challenger} placeholder="Choose a team" required onChange={(ev) => setChallenger(ev.target.value)} options={teams} />
            <Select label="Defender" value={defender} placeholder="Choose a team" required onChange={(ev) => setDefender(ev.target.value)} options={teams} />
            <Button type="submit" loading={challenge.isPending} disabled={!challenger || !defender}>Add challenge</Button>
          </form>
          <p className="mt-3 text-sm text-muted">A team may challenge up to {competition.ladder_challenge_range ?? 3} rungs above it; a win swaps the two rungs.</p>
        </Card>
      )}
      <List<Schemas['LadderRungOut']>
        caption="Ladder"
        rows={ladder.data}
        rowKey={(r) => r.competition_team_id}
        empty="The ladder is empty"
        columns={[{ header: 'Rung', cell: (r) => r.position }, { header: 'Team', cell: (r) => r.team_name ?? '—' }]}
      />
    </div>
  )
}

// ---------------------------------------------------------------- team preferences (LGE-10), fee split (REG-26)

type Pref = { kind: 'date' | 'weekday' | 'time' | 'resource'; value: string; wants: boolean; is_priority: boolean }
const PREF_HINT = { date: 'YYYY-MM-DD', weekday: '1 (Monday) to 7 (Sunday)', time: 'HH:MM-HH:MM', resource: 'Choose a court or venue' }

export function PreferencesDialog({ entry, competition, onClose }: { entry: Entry; competition: Competition; onClose: () => void }) {
  const toast = useToast()
  const places = usePlaces(competition.location_id)
  const saved = useQuery({ queryKey: ['preferences', entry.id], queryFn: () => api.get('/api/v1/competition-teams/{competition_team_id}/preferences', { path: { competition_team_id: entry.id } }) })
  const [rows, setRows] = useState<Pref[] | null>(null)
  const list: Pref[] = rows ?? (saved.data ?? []).map((p) => ({ kind: p.kind as Pref['kind'], value: p.value, wants: p.wants, is_priority: p.is_priority }))
  const edit = (i: number, patch: Partial<Pref>) => setRows(list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/competition-teams/{competition_team_id}/preferences', { path: { competition_team_id: entry.id }, body: { preferences: list } }),
    onSuccess: () => { toast('success', `Preferences for ${entry.name} saved.`); onClose() },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog open size="lg" onClose={onClose} title={`Scheduling preferences: ${entry.name}`} description="The generator tries to give the team what it prefers and avoid what it cannot play; a priority weighs double." footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate()} loading={save.isPending}>Save preferences</Button></>}>
      <Alert error={save.error} />
      {saved.isPending ? <LoadingState /> : (
        <div className="space-y-3">
          {list.map((p, i) => (
            <div key={i} className="grid gap-3 rounded border border-border p-3 sm:grid-cols-4 sm:items-end">
              <Select label={`Preference ${i + 1} kind`} value={p.kind} onChange={(ev) => edit(i, { kind: ev.target.value as Pref['kind'], value: '' })} options={[{ value: 'date', label: 'Date' }, { value: 'weekday', label: 'Weekday' }, { value: 'time', label: 'Time of day' }, { value: 'resource', label: 'Court or venue' }]} />
              {p.kind === 'resource' ? (
                <Select label={`Preference ${i + 1} value`} value={p.value} placeholder={PREF_HINT.resource} error={e[`preferences/${i}/value`]} onChange={(ev) => edit(i, { value: ev.target.value })} options={places.map((o) => ({ value: o.value.slice(2), label: o.label }))} />
              ) : (
                <Input label={`Preference ${i + 1} value`} value={p.value} hint={PREF_HINT[p.kind]} error={e[`preferences/${i}/value`]} onChange={(ev) => edit(i, { value: ev.target.value })} />
              )}
              <Select label={`Preference ${i + 1} meaning`} value={p.wants ? 'wants' : 'cannot'} onChange={(ev) => edit(i, { wants: ev.target.value === 'wants' })} options={[{ value: 'wants', label: 'Prefers this' }, { value: 'cannot', label: 'Cannot play then' }]} />
              <div className="flex items-center gap-3">
                <Checkbox label="Priority" checked={p.is_priority} onChange={(ev) => edit(i, { is_priority: ev.target.checked })} />
                <Button size="sm" variant="secondary" aria-label={`Remove preference ${i + 1}`} onClick={() => setRows(list.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            </div>
          ))}
          <Button variant="secondary" onClick={() => setRows([...list, { kind: 'weekday', value: '', wants: false, is_priority: false }])}>Add a preference</Button>
        </div>
      )}
    </Dialog>
  )
}

export function FeeSplitDialog({ entry, competition, onClose }: { entry: Entry; competition: Competition; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const roster = useQuery({ queryKey: ['roster', entry.id], queryFn: () => api.get('/api/v1/competition-teams/{competition_team_id}/roster', { path: { competition_team_id: entry.id } }) })
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const [payer, setPayer] = useState<ClientSummary | null>(null)
  const fee = competition.team_fee_minor ?? 0
  const shares = Object.entries(amounts).map(([id, v]) => ({ roster_entry_id: id, amount_minor: toMinor(v) ?? 0 })).filter((s) => s.amount_minor > 0)
  const rest = fee - shares.reduce((sum, s) => sum + s.amount_minor, 0)
  const split = useMutation({
    mutationFn: () => api.post('/api/v1/competition-teams/{competition_team_id}/fee-shares', { path: { competition_team_id: entry.id }, body: { shares, bill_to_client_id: payer?.id ?? null } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['competition', competition.id] }); toast('success', `The fee for ${entry.name} is split and invoiced.`); onClose() },
  })
  const players = (roster.data ?? []).filter((r) => r.client_id && r.status === 'active')
  return (
    <Dialog open size="lg" onClose={onClose} title={`Split the fee for ${entry.name}`} description={`${formatMoney(fee)} in all; each share is invoiced to its player.`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => split.mutate()} loading={split.isPending} disabled={!shares.length || rest < 0}>Split and invoice</Button></>}>
      <Alert error={split.error} />
      {roster.isPending ? <LoadingState /> : players.length === 0 ? <EmptyState title="No rostered clients to share the fee" /> : (
        <div className="grid gap-3 sm:grid-cols-2">
          {players.map((r) => <Input key={r.id} label={`Share for ${r.name} ($)`} inputMode="decimal" value={amounts[r.id] ?? ''} onChange={(ev) => setAmounts({ ...amounts, [r.id]: ev.target.value })} />)}
          <p role="status" className="sm:col-span-2">{rest >= 0 ? `${formatMoney(rest)} left over.` : `${formatMoney(-rest)} more than the fee.`}</p>
          {rest > 0 && <ClientPicker label="Bill what is left over to" value={payer} onChange={setPayer} required error={fieldErrors(split.error).bill_to_client_id} />}
        </div>
      )}
    </Dialog>
  )
}

// ---------------------------------------------------------------- publish a program group (REG-14)

export function PublishGroupDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const sports = useSports()
  const groups = useQuery({ queryKey: ['program-groups', locationId, 'active'], queryFn: () => api.get('/api/v1/program-groups', { query: { location_id: locationId, status: 'active', limit: 200 } }) })
  const [f, setF] = useState({ program_group_id: '', kind: 'league', sport_id: '', starts_on: '' })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const publish = useMutation({
    mutationFn: () => api.post('/api/v1/competitions/from-program-group', { body: { program_group_id: f.program_group_id, kind: f.kind as 'league' | 'tournament', format: 'round_robin', sport_id: f.sport_id, starts_on: f.starts_on, include_players: true } }),
    onSuccess: (row) => { void qc.invalidateQueries({ queryKey: ['competitions'] }); toast('success', `${row.name} created from the program.`); onClose() },
  })
  const e = fieldErrors(publish.error)
  return (
    <Dialog open size="lg" onClose={onClose} title="Publish a program as a competition" description="Each sub-group becomes a team and its enrolled players its roster. It is a one-off copy." footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="publish-form" loading={publish.isPending}>Publish</Button></>}>
      <form id="publish-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => { ev.preventDefault(); publish.mutate() }}>
        <Alert error={publish.error} />
        <Select label="Program" value={f.program_group_id} placeholder="Choose a program" required error={e.program_group_id} onChange={(ev) => set({ program_group_id: ev.target.value })} options={(groups.data?.data ?? []).filter((g) => !g.parent_id).map((g) => ({ value: g.id, label: g.name }))} />
        <Select label="Publish as" value={f.kind} onChange={(ev) => set({ kind: ev.target.value })} options={[{ value: 'league', label: 'League' }, { value: 'tournament', label: 'Tournament' }]} />
        <Select label="Sport" value={f.sport_id} placeholder="Choose a sport" required error={e.sport_id} onChange={(ev) => set({ sport_id: ev.target.value })} options={(sports.data?.data ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        <Input label="Starts on" type="date" value={f.starts_on} required error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
      </form>
    </Dialog>
  )
}

/** A blank card for a pickup or makeup game, with both rosters to pick from (LGE-16). */
export function BlankCardButton({ competition }: { competition: Competition }) {
  const toast = useToast()
  return (
    <Button variant="secondary" onClick={() => downloadFile('/api/v1/competitions/{competition_id}/blank-game-card', { path: { competition_id: competition.id } }, 'blank-game-card.pdf').catch((e: Error) => toast('error', e.message))}>
      Blank game card
    </Button>
  )
}
