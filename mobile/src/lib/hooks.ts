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

/** The acting client's home location, else the first location. */
export function useHomeLocation() {
  const { data } = useLocations();
  const { actingFor } = useHousehold();
  return data?.find((l) => l.id === actingFor?.client.home_location_id) ?? data?.[0];
}

/** Zone for schedule times: the home location's (above), else UTC. */
export function useZone(): string {
  return useHomeLocation()?.time_zone ?? 'UTC';
}

/** getPublicAppConfig for the active facility: home layout and feature switches (the theme is applied by
 * app-state through fetchBrand). Null while unavailable, so screens fall back to their built-in behaviour. */
export function useAppConfig() {
  const { tenant } = useApp();
  return useQuery({
    queryKey: ['app-config', tenant?.slug],
    queryFn: () => portal.getAppConfig(),
    enabled: !!tenant && !portal.isDemo,
    staleTime: 5 * 60_000,
    retry: false,
  });
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
