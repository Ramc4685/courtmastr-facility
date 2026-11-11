import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'

export type Competition = Schemas['CompetitionOut']
export type Sport = Schemas['SportOut']
export type Entry = Schemas['CompetitionTeamOut']
export type Game = Schemas['GameOut']
export type Standing = Schemas['LeagueStandingOut']
export type Bracket = Schemas['BracketOut']

export const STATUS_TONE: Record<string, 'neutral' | 'success' | 'warning' | 'info' | 'danger'> = {
  draft: 'neutral', active: 'success', completed: 'info', archived: 'neutral',
  proposed: 'neutral', scheduled: 'info', played: 'success', postponed: 'warning', unschedulable: 'danger', cancelled: 'neutral', bye: 'neutral',
}
export const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ')

export const useSports = () => useQuery({ queryKey: ['sports'], queryFn: () => api.get('/api/v1/sports', { query: { limit: 200 } }) })

export const useCompetition = (id: string) =>
  useQuery({ queryKey: ['competition', id], queryFn: () => api.get('/api/v1/competitions/{competition_id}', { path: { competition_id: id } }) })

export const useEntries = (id: string) =>
  useQuery({ queryKey: ['competition', id, 'teams'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/teams', { path: { competition_id: id } }) })

// shortcut: one page of 200 games covers a season of a league of 20 teams; page it when competitions grow.
export const useGames = (id: string) =>
  useQuery({ queryKey: ['competition', id, 'games'], queryFn: () => api.get('/api/v1/games', { query: { competition_id: id, limit: 200 } }) })

export const useStandings = (id: string) =>
  useQuery({ queryKey: ['competition', id, 'standings'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/standings', { path: { competition_id: id } }) })

export const useBrackets = (id: string) =>
  useQuery({ queryKey: ['competition', id, 'brackets'], queryFn: () => api.get('/api/v1/competitions/{competition_id}/brackets', { path: { competition_id: id } }) })
