/** The captain's roster in the client portal (REG-26): a team captain adds household members or walk-on
 * players to the roster of the team they captain, and removes them. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDate } from '../../lib/format'
import { clientName, usePortalClients } from '../portal/shared'
import { Alert, List } from './shared'

type Team = Schemas['PortalLeagueTeamOut']
type Player = Schemas['PortalRosterEntryOut']
const WALK_ON = 'walk-on'
const BLANK = { who: '', first_name: '', last_name: '', jersey_number: '' }

function TeamRoster({ team }: { team: Team }) {
  const qc = useQueryClient()
  const toast = useToast()
  const clients = usePortalClients()
  const key = ['portal', 'league-roster', team.competition_team_id]
  const roster = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/portal/league-teams/{competition_team_id}/roster', { path: { competition_team_id: team.competition_team_id } }) })
  const [f, setF] = useState(BLANK)
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const walkOn = f.who === WALK_ON
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/portal/league-teams/{competition_team_id}/roster', {
      path: { competition_team_id: team.competition_team_id },
      body: walkOn ? { first_name: f.first_name, last_name: f.last_name, jersey_number: f.jersey_number || null } : { client_id: f.who, jersey_number: f.jersey_number || null },
    }),
    onSuccess: (row) => { void qc.invalidateQueries({ queryKey: key }); toast('success', `${row.name} added to ${team.team_name}.`); setF(BLANK) },
  })
  const remove = useMutation({
    mutationFn: (p: Player) => api.delete('/api/v1/portal/league-roster-entries/{roster_entry_id}', { path: { roster_entry_id: p.id } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast('success', 'Player removed.') },
    onError: (e: Error) => toast('error', e.message),
  })
  const e = fieldErrors(add.error)
  return (
    <Card title={`${team.team_name} · ${team.competition_name}`}>
      <p className="mb-4 text-sm text-muted">Starts {formatDate(team.starts_on)}.</p>
      {roster.isPending ? <LoadingState /> : roster.isError ? <ErrorState error={roster.error} onRetry={() => roster.refetch()} /> : (
        <List<Player>
          caption={`${team.team_name} roster`}
          rows={roster.data}
          rowKey={(p) => p.id}
          empty="No players yet"
          columns={[
            { header: 'Player', cell: (p) => p.name },
            { header: 'Number', cell: (p) => p.jersey_number ?? '—' },
            { header: 'Actions', cell: (p) => <Button size="sm" variant="secondary" aria-label={`Remove ${p.name}`} onClick={() => remove.mutate(p)}>Remove</Button> },
          ]}
        />
      )}
      <form className="mt-4 grid gap-3 sm:grid-cols-4 sm:items-end" noValidate aria-label={`Add a player to ${team.team_name}`} onSubmit={(ev) => { ev.preventDefault(); add.mutate() }}>
        <Alert error={add.error} />
        <Select label="Player" value={f.who} placeholder="Choose a player" required error={e.client_id} onChange={(ev) => set({ who: ev.target.value })} options={[...(clients.data?.data ?? []).map((c) => ({ value: c.id, label: clientName(c) })), { value: WALK_ON, label: 'Someone else' }]} />
        {walkOn && <Input label="First name" value={f.first_name} required error={e.first_name} onChange={(ev) => set({ first_name: ev.target.value })} />}
        {walkOn && <Input label="Last name" value={f.last_name} required error={e.last_name} onChange={(ev) => set({ last_name: ev.target.value })} />}
        <Input label="Number" value={f.jersey_number} error={e.jersey_number} onChange={(ev) => set({ jersey_number: ev.target.value })} />
        <div><Button type="submit" loading={add.isPending} disabled={!f.who}>Add player</Button></div>
      </form>
    </Card>
  )
}

export function CaptainPage() {
  const teams = useQuery({ queryKey: ['portal', 'league-teams'], queryFn: () => api.get('/api/v1/portal/league-teams') })
  return (
    <>
      <PageHeader title="My teams" description="Teams you captain. Add your players; the club sees the roster at once." />
      {teams.isPending ? <LoadingState /> : teams.isError ? <ErrorState error={teams.error} onRetry={() => teams.refetch()} /> : teams.data.length === 0 ? (
        <EmptyState title="You do not captain a team">The club names a team's captain when the team enters a league.</EmptyState>
      ) : (
        <div className="space-y-6">{teams.data.map((t) => <TeamRoster key={t.competition_team_id} team={t} />)}</div>
      )}
    </>
  )
}
