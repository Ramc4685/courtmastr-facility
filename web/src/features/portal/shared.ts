import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'

export type PortalClient = Schemas['PortalClientOut']

/** The signed-in person and the dependents they may book for. */
export const usePortalClients = () => useQuery({ queryKey: ['portal', 'clients'], queryFn: () => api.get('/api/v1/portal/clients') })

export const clientName = (c: { first_name: string; last_name: string; preferred_name: string | null }) => `${c.preferred_name || c.first_name} ${c.last_name}`.trim()
