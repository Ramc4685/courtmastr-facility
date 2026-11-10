import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

// Small reference lists used by selects and editors; one page of 200 covers them comfortably.
export const useAllLocations = () =>
  useQuery({ queryKey: ['locations', 'all'], queryFn: () => api.get('/api/v1/locations', { query: { limit: 200, sort: 'name' } }) })

export const useAllRoles = (enabled = true) =>
  useQuery({ queryKey: ['roles', 'all'], queryFn: () => api.get('/api/v1/roles', { query: { limit: 200 } }), enabled })

export const useCatalogue = () => useQuery({ queryKey: ['permissions'], queryFn: () => api.get('/api/v1/permissions'), staleTime: Infinity })
