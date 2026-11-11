import { useQuery } from '@tanstack/react-query';

import { portal } from '../adapters';
import { api, unwrap } from '../api/client';
import { useApp } from './app-state';
import { useHousehold } from './household';

/** Real: GET /public/locations for the active tenant. */
export function useLocations() {
  const { tenant } = useApp();
  return useQuery({
    queryKey: ['locations', tenant?.slug],
    queryFn: async () => (await unwrap(api().GET('/api/v1/public/locations', { params: { query: { limit: 50 } } }))).data,
    enabled: !!tenant,
    staleTime: 10 * 60_000,
  });
}

/** Zone for schedule times: the acting client's home location, else the first location, else the tenant's. */
export function useZone(): string {
  const { data } = useLocations();
  const { actingFor } = useHousehold();
  const home = data?.find((l) => l.id === actingFor?.client.home_location_id);
  return home?.time_zone ?? data?.[0]?.time_zone ?? 'UTC';
}

export function useInbox() {
  const { tenant } = useApp();
  return useQuery({ queryKey: ['inbox', tenant?.slug], queryFn: () => portal.listInbox() });
}

export function useBookings() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const clientId = actingFor?.client.id;
  return useQuery({
    queryKey: ['bookings', tenant?.slug, clientId],
    queryFn: () => portal.listBookings(clientId!),
    enabled: !!clientId,
  });
}
