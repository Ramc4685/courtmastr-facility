import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Navigate, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, resource, SCREEN } from '../scheduling/testing'
import { CaptainPage } from './CaptainPage'
import { ScoresPage, StatsPage, VenuesPage } from './depth'
import { LeaguePage } from './LeaguesPage'

const ALL = ['leagues.competition.manage', 'leagues.team.manage', 'leagues.schedule.generate', 'leagues.result.enter', 'leagues.game.manage', 'leagues.game_card.print']
const competition = {
  id: 'c1', location_id: 'l1', kind: 'league', format: 'round_robin', name: 'Wednesday Futsal', sport_id: 'sp1', status: 'active',
  starts_on: '2031-05-01', ends_on: '2031-06-30', team_fee_minor: 30000, revenue_category_id: 'rc1', is_public: true,
}
const game = {
  id: 'g1', competition_id: 'c1', competition_name: 'Wednesday Futsal', location_id: 'l1', home_team_id: 't1', away_team_id: 't2', home_name: 'Strikers', away_name: 'Rovers',
  home_label: null, away_label: null, starts_at: '2031-05-07T23:00:00Z', ends_at: '2031-05-08T00:00:00Z', status: 'scheduled', is_bye: false,
  home_score: null, away_score: null, version: 1,
}
const venue = { id: 'v1', location_id: 'l1', name: 'Twin courts', description: null, resource_ids: ['r1', 'r2'], is_active: true }
const at = (path: string, element: JSX.Element) => (
  <Routes>
    <Route path="/" element={<Navigate to={path} />} />
    <Route path="/leagues/:id" element={element} />
  </Routes>
)

describe('league depth screens', SCREEN, () => {
  it('generates over several windows with a venue and a bye mode, then books the games', async () => {
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: competition },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [] },
      'GET /api/v1/games': page([]),
      'GET /api/v1/resources': page([resource('r1', 'Court 1'), resource('r2', 'Court 2')]),
      'GET /api/v1/league-venues': page([venue]),
      'POST /api/v1/schedule-runs': { status: 201, body: { id: 'run1', state: 'draft' } },
      'POST /api/v1/schedule-runs/run1/generate': { status: 200, body: { id: 'run1', state: 'generating', progress: { done: 0, total: 1 } } },
      'GET /api/v1/schedule-runs/run1': { status: 200, body: { id: 'run1', state: 'previewed', progress: { done: 1, total: 1 }, stats: { games: 6, byes: 0, unschedulable: 0, predicted_completion_on: '2031-06-11' } } },
      'POST /api/v1/schedule-runs/run1/commit': { status: 200, body: { id: 'run1', state: 'committed', stats: { booked: 6 } } },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Schedule & results' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Generate schedule' }))
    const dialog = await screen.findByRole('dialog', { name: 'Generate the schedule' })
    await within(dialog).findByRole('option', { name: 'Twin courts (venue)' })
    await userEvent.selectOptions(within(dialog).getByLabelText('Window 1 court or venue'), 'v:v1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add a window' }))
    await userEvent.selectOptions(within(dialog).getByLabelText('Window 2 court or venue'), 'r:r1')
    await userEvent.selectOptions(within(dialog).getByLabelText('Window 2 day'), '6')
    await userEvent.selectOptions(within(dialog).getByLabelText('Odd number of teams'), 'fold_last_round')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview' }))
    expect(await within(dialog).findByText(/6 games proposed; the last game is on/)).toBeVisible()
    expect(calls.find((c) => c.method === 'POST' && c.url.endsWith('/schedule-runs'))?.body).toMatchObject({
      resource_ids: ['r1'], bye_mode: 'fold_last_round',
      time_slots: [{ weekday: 3, starts_at: '18:00', ends_at: '22:00', venue_id: 'v1' }, { weekday: 6, starts_at: '18:00', ends_at: '22:00', resource_id: 'r1' }],
    })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Book the games' }))
    expect(await screen.findByText('6 games booked.')).toBeVisible()
  })

  it('draws a double elimination bracket with a reset game', async () => {
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: { ...competition, kind: 'tournament', format: 'double_elimination' } },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [] },
      'GET /api/v1/competitions/c1/brackets': { status: 200, body: [] },
      'POST /api/v1/competitions/c1/brackets': { status: 201, body: { id: 'b1', slots: [] } },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Bracket' }))
    expect(await screen.findByRole('combobox', { name: 'Bracket' })).toHaveValue('double_elimination')
    await userEvent.click(screen.getByRole('button', { name: 'Draw a bracket' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ bracket_type: 'double_elimination', seed_source: 'seeds', has_reset_game: true, advance_per_pool: null })
  })

  it('assigns a scorekeeper to the competition', async () => {
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: competition },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [] },
      'GET /api/v1/competitions/c1/staff': { status: 200, body: [] },
      'GET /api/v1/competitions/c1/staff-candidates': { status: 200, body: [{ id: 'u1', name: 'Sam Keeper' }] },
      'PUT /api/v1/competitions/c1/staff': { status: 200, body: [{ id: 'cs1', competition_id: 'c1', staff_user_id: 'u1', role: 'scorekeeper' }] },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Staff' }))
    await screen.findByRole('option', { name: 'Sam Keeper' })
    await userEvent.selectOptions(screen.getByLabelText('Staff member'), 'u1')
    await userEvent.click(screen.getByRole('button', { name: 'Assign' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ staff: [{ staff_user_id: 'u1', role: 'scorekeeper' }] })
  })

  it('groups courts into a venue', async () => {
    const calls = renderAsStaff(<VenuesPage />, ALL, {
      'GET /api/v1/resources': page([resource('r1', 'Court 1'), resource('r2', 'Court 2')]),
      'GET /api/v1/league-venues': page([venue]),
      'POST /api/v1/league-venues': { status: 201, body: { ...venue, id: 'v2', name: 'Both' } },
    })
    expect(within(await screen.findByRole('table', { name: 'Venues' })).getByRole('row', { name: /Twin courts/ })).toHaveTextContent('Court 1, Court 2')
    await userEvent.type(screen.getByLabelText('Venue name'), 'Both')
    await userEvent.click(screen.getByLabelText('Court 1'))
    await userEvent.click(screen.getByLabelText('Court 2'))
    await userEvent.click(screen.getByRole('button', { name: 'Add venue' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ location_id: 'l1', name: 'Both', resource_ids: ['r1', 'r2'], is_active: true })
  })

  it('adds a formula stat to a stat table', async () => {
    const calls = renderAsStaff(<StatsPage />, ALL, {
      'GET /api/v1/sports': page([{ id: 'sp1', name: 'Futsal', is_active: true }]),
      'GET /api/v1/sports/sp1/stat-tables': { status: 200, body: [{ id: 'st1', sport_id: 'sp1', name: 'Scoring', sort_order: 0, stats: [
        { id: 'd1', stat_table_id: 'st1', sport_id: 'sp1', code: 'G', name: 'Goals', kind: 'entry', formula: null, decimal_places: 0, sort_order: 0 },
      ] }] },
      'POST /api/v1/stat-tables/st1/stats': { status: 201, body: { id: 'd2', name: 'Goals per game' } },
    })
    const form = await screen.findByRole('form', { name: 'Add a stat to Scoring' })
    await userEvent.type(within(form).getByLabelText('Code'), 'gpg')
    await userEvent.type(within(form).getByLabelText('Stat name'), 'Goals per game')
    await userEvent.selectOptions(within(form).getByLabelText('Kind'), 'formula')
    await userEvent.type(within(form).getByLabelText('Formula'), 'G / GP')
    await userEvent.click(within(form).getByRole('button', { name: 'Add stat' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ code: 'GPG', kind: 'formula', formula: 'G / GP', sort_order: 1 })
  })

  it('shows a scorekeeper only their games and enters a score', async () => {
    const calls = renderAsStaff(<ScoresPage />, ['leagues.result.enter', 'leagues.game_card.print'], {
      'GET /api/v1/games': page([game]),
      'PUT /api/v1/games/g1/result': { status: 200, body: { game_id: 'g1' } },
    })
    const row = within(await screen.findByRole('table', { name: 'Games to score' })).getByRole('row', { name: /Strikers vs Rovers/ })
    expect(row).toHaveTextContent('Wednesday Futsal')
    expect(within(row).getByRole('button', { name: 'Print the game card of Strikers vs Rovers' })).toBeVisible()
    await userEvent.click(within(row).getByRole('button', { name: 'Enter the score of Strikers vs Rovers' }))
    const dialog = await screen.findByRole('dialog', { name: 'Score: Strikers vs Rovers' })
    await userEvent.type(within(dialog).getByLabelText('Strikers score'), '2')
    await userEvent.type(within(dialog).getByLabelText('Rovers score'), '0')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save result' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
  })

  it('lets a captain add a walk-on player in the portal', async () => {
    const calls = renderAsStaff(<CaptainPage />, [], {
      'GET /api/v1/portal/league-teams': { status: 200, body: [{ competition_team_id: 't1', team_name: 'Caps', competition_name: 'Wednesday Futsal', starts_on: '2031-05-01' }] },
      'GET /api/v1/portal/clients': page([{ id: 'p1', first_name: 'Cara', last_name: 'Captain', preferred_name: null }]),
      'GET /api/v1/portal/league-teams/t1/roster': { status: 200, body: [{ id: 'e1', name: 'Cara Captain', role: 'captain', jersey_number: '1' }] },
      'POST /api/v1/portal/league-teams/t1/roster': { status: 201, body: { id: 'e2', name: 'Walk On', role: 'player', jersey_number: '9' } },
    })
    expect(within(await screen.findByRole('table', { name: 'Caps roster' })).getByRole('row', { name: /Cara Captain/ })).toBeVisible()
    const form = screen.getByRole('form', { name: 'Add a player to Caps' })
    await userEvent.selectOptions(within(form).getByLabelText('Player'), 'walk-on')
    await userEvent.type(within(form).getByLabelText('First name'), 'Walk')
    await userEvent.type(within(form).getByLabelText('Last name'), 'On')
    await userEvent.type(within(form).getByLabelText('Number'), '9')
    await userEvent.click(within(form).getByRole('button', { name: 'Add player' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ first_name: 'Walk', last_name: 'On', jersey_number: '9' })
  })
})
