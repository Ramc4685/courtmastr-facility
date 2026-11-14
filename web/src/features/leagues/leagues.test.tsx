import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Navigate, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, resource, SCREEN } from '../scheduling/testing'
import { LeaguePage, LeaguesPage } from './LeaguesPage'
import { PublicLeaguesPage } from './PublicLeaguesPage'

const ALL = ['leagues.competition.manage', 'leagues.team.manage', 'leagues.schedule.generate', 'leagues.result.enter', 'leagues.game.manage']
const sport = { id: 'sp1', name: 'Futsal', is_active: true, default_game_length_min: 60 }
const competition = {
  id: 'c1', location_id: 'l1', kind: 'league', format: 'round_robin', name: 'Wednesday Futsal', sport_id: 'sp1', status: 'active',
  starts_on: '2031-05-01', ends_on: '2031-06-30', team_fee_minor: 30000, revenue_category_id: 'rc1', is_public: true,
}
const game = {
  id: 'g1', competition_id: 'c1', location_id: 'l1', home_team_id: 't1', away_team_id: 't2', home_name: 'Strikers', away_name: 'Rovers',
  home_label: null, away_label: null, starts_at: '2031-05-07T23:00:00Z', ends_at: '2031-05-08T00:00:00Z', status: 'scheduled', is_bye: false,
  home_score: null, away_score: null, version: 1,
}
const at = (path: string, element: JSX.Element) => (
  <Routes>
    <Route path="/" element={<Navigate to={path} />} />
    <Route path="/leagues/:id" element={element} />
    <Route path="/leagues/public/:id" element={element} />
  </Routes>
)

describe('LeaguesPage', SCREEN, () => {
  it('lists competitions and creates a league with a team fee', async () => {
    const calls = renderAsStaff(<LeaguesPage />, ALL, {
      'GET /api/v1/competitions': page([competition]),
      'GET /api/v1/sports': page([sport]),
      'GET /api/v1/revenue-categories': page([{ id: 'rc1', label: 'Programs', is_active: true }]),
      'POST /api/v1/competitions': { status: 201, body: { ...competition, id: 'c2', name: 'Thursday Hoops', status: 'draft' } },
    })
    const row = within(await screen.findByRole('table', { name: 'Competitions' })).getByRole('row', { name: /Wednesday Futsal/ })
    expect(row).toHaveTextContent('Futsal')
    expect(row).toHaveTextContent('Active')
    await userEvent.click(screen.getByRole('button', { name: 'New competition' }))
    const dialog = await screen.findByRole('dialog', { name: 'New competition' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Thursday Hoops')
    await userEvent.selectOptions(within(dialog).getByLabelText('Sport'), 'sp1')
    await userEvent.type(within(dialog).getByLabelText('Starts on'), '2031-09-01')
    await userEvent.type(within(dialog).getByLabelText('Team fee ($)'), '250')
    await userEvent.selectOptions(within(dialog).getByLabelText('Revenue category'), 'rc1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create competition' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      location_id: 'l1', kind: 'league', format: 'round_robin', name: 'Thursday Hoops', sport_id: 'sp1', starts_on: '2031-09-01',
      team_fee_minor: 25000, revenue_category_id: 'rc1', is_public: true,
    })
  })

  it('enters a score from the schedule and bills an unbilled team fee', async () => {
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: competition },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [
        { id: 't1', name: 'Strikers', seed: 1, display_name: null, fee_status: 'billed', competition_id: 'c1' },
        { id: 't2', name: 'Rovers', seed: 2, display_name: null, fee_status: 'unbilled', competition_id: 'c1' },
      ] },
      'GET /api/v1/games': page([game]),
      'PUT /api/v1/games/g1/result': { status: 200, body: { game_id: 'g1', status: 'played' } },
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Wednesday Futsal' })).toBeVisible()
    const teams = await screen.findByRole('table', { name: 'Teams' })
    expect(within(teams).getByRole('row', { name: /Rovers/ })).toHaveTextContent('Unbilled')
    expect(within(teams).getByRole('button', { name: 'Bill the fee for Rovers' })).toBeVisible()
    await userEvent.click(screen.getByRole('tab', { name: 'Schedule & results' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Enter the score of Strikers vs Rovers' }))
    const dialog = await screen.findByRole('dialog', { name: 'Score: Strikers vs Rovers' })
    await userEvent.type(within(dialog).getByLabelText('Strikers score'), '3')
    await userEvent.type(within(dialog).getByLabelText('Rovers score'), '1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save result' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      home: { score: 3, participation: 'full', went_to_overtime: false, bonus_points: 0 },
      away: { score: 1, participation: 'full', went_to_overtime: false, bonus_points: 0 },
    })
  })

  it('scores a sets competition set by set, ranks by sets and switches the format by preset', async () => {
    const sets = { ...competition, scoring_mode: 'sets', sets_best_of: 3, set_points_to: 21, set_win_by: 2, set_cap: 30, deciding_set_points_to: null }
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: sets },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [] },
      'GET /api/v1/games': page([{ ...game, sets_best_of: 3, set_scores: null }]),
      'GET /api/v1/competitions/c1/standings': { status: 200, body: [
        { id: 's1', rank: 1, team_name: 'Strikers', games_played: 1, wins: 1, losses: 0, ties: 0, goals_for: 2, goals_against: 1, goal_difference: 1, points: '3.00', set_points_for: 61, set_points_against: 54 },
      ] },
      'PUT /api/v1/games/g1/result': { status: 200, body: { game_id: 'g1', status: 'played' } },
      'PATCH /api/v1/competitions/c1': { status: 200, body: sets },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Schedule & results' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Enter the score of Strikers vs Rovers' }))
    const dialog = await screen.findByRole('dialog', { name: 'Score: Strikers vs Rovers' })
    // a set with one side blank is refused, never saved as 21-0
    await userEvent.type(within(dialog).getByLabelText('Set 1: Strikers'), '21')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save result' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Set 1 needs a score for both sides')
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    await userEvent.clear(within(dialog).getByLabelText('Set 1: Strikers'))
    for (const [field, value] of [['Set 1: Strikers', '21'], ['Set 1: Rovers', '18'], ['Set 2: Strikers', '19'], ['Set 2: Rovers', '21'], ['Set 3: Strikers', '21'], ['Set 3: Rovers', '15']] as const) {
      await userEvent.type(within(dialog).getByLabelText(field), value)
    }
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save result' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const side = { participation: 'full', went_to_overtime: false, bonus_points: 0 }
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ home: { ...side, sets: [21, 19, 21] }, away: { ...side, sets: [18, 21, 15] } })

    await userEvent.click(screen.getByRole('tab', { name: 'Standings' }))
    const row = within(await screen.findByRole('table', { name: 'Standings' })).getByRole('row', { name: /Strikers/ })
    expect(row).toHaveTextContent('2.00')
    expect(row).toHaveTextContent('1.13')
    await userEvent.click(screen.getByRole('button', { name: 'Scoring format' }))
    const format = await screen.findByRole('dialog', { name: 'Scoring format' })
    await userEvent.click(within(format).getByRole('button', { name: 'Volleyball, best of 5' }))
    await userEvent.click(within(format).getByRole('button', { name: 'Save format' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      scoring_mode: 'sets', sets_best_of: 5, set_points_to: 25, set_win_by: 2, set_cap: null, deciding_set_points_to: 15,
      forfeit_score_for: 3, // best of 3 to best of 5: a forfeit now counts as three sets
    })
  })

  it('holds a league night on chosen courts and tells staff to re-block a moved game', async () => {
    const calls = renderAsStaff(at('/leagues/c1', <LeaguePage />), ALL, {
      'GET /api/v1/competitions/c1': { status: 200, body: competition },
      'GET /api/v1/competitions/c1/teams': { status: 200, body: [] },
      'GET /api/v1/games': page([]),
      'GET /api/v1/resources': page([resource('r1', 'Court 1'), resource('r2', 'Court 2')]),
      'POST /api/v1/competitions/c1/league-nights': { status: 201, body: {
        booking_id: 'b1', competition_id: 'c1', title: 'Wednesday Futsal league night', starts_at: '2031-05-07T23:00:00Z', ends_at: '2031-05-08T03:00:00Z', resource_ids: ['r2'],
      } },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Schedule & results' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Hold a league night' }))
    const dialog = await screen.findByRole('dialog', { name: 'Hold a league night' })
    expect(dialog).toHaveTextContent('If you move or postpone a game, re-block its old slot.')
    expect(within(dialog).getByRole('button', { name: 'Hold courts' })).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('From'), '2031-05-07T18:00')
    await userEvent.type(within(dialog).getByLabelText('Until'), '2031-05-07T22:00')
    await userEvent.click(await within(dialog).findByLabelText('Court 2'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Hold courts' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      resource_ids: ['r2'], starts_at: '2031-05-07T23:00:00Z', ends_at: '2031-05-08T03:00:00Z', // Chicago's wall time, whatever the browser's zone
    })
  })
})

describe('PublicLeaguesPage', SCREEN, () => {
  it('shows the standings and schedule of a public competition', async () => {
    renderAsStaff(at('/leagues/public/c1', <PublicLeaguesPage />), [], {
      'GET /api/v1/public/competitions/c1': { status: 200, body: { ...competition, sport_name: 'Futsal', team_fee_text: '$300 per team' } },
      'GET /api/v1/public/competitions/c1/standings': { status: 200, body: [
        { division_name: 'Main', rank: 1, team_name: 'Strikers', games_played: 1, wins: 1, losses: 0, ties: 0, goals_for: 3, goals_against: 1, goal_difference: 2, win_pct: '1.000', points: '3.00' },
      ] },
      'GET /api/v1/public/competitions/c1/games': { status: 200, body: [
        { id: 'g1', starts_at: game.starts_at, ends_at: game.ends_at, venue: 'Court 3', status: 'played', round_label: null, home_name: 'Strikers', away_name: 'Rovers', home_score: 3, away_score: 1 },
      ] },
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Wednesday Futsal' })).toBeVisible()
    const table = await screen.findByRole('table', { name: 'Standings' })
    expect(within(table).getByRole('row', { name: /Strikers/ })).toHaveTextContent('3')
    expect(await screen.findByText('Strikers 3 - 1 Rovers')).toBeVisible()
    expect(screen.getByText('Team fee: $300 per team')).toBeVisible()
  })
})
