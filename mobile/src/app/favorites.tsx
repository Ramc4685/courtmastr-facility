import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { portal } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { formatDateTime } from '../ui/format';
import { Badge, Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

const DAY = 86_400_000;
const KIND_LABEL: Record<string, string> = { program_group: 'Program', reservation_type: 'Booking type' };

/** APP-13: the acting client's favourites and the sessions they match in the next 14 days. */
export default function Favorites() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const clientId = actingFor?.client.id;
  const qc = useQueryClient();
  const favorites = useQuery({ queryKey: ['favorites', tenant?.slug, clientId], queryFn: () => portal.listFavorites(clientId!), enabled: !!clientId });
  const schedule = useQuery({
    queryKey: ['favorite-schedule', tenant?.slug, clientId],
    queryFn: () => {
      const now = Date.now();
      return portal.listFavoriteSchedule({ clientId: clientId!, from: new Date(now).toISOString(), to: new Date(now + 14 * DAY).toISOString() });
    },
    enabled: !!clientId,
  });
  const remove = useMutation({
    mutationFn: (id: string) => portal.removeFavorite(id),
    onSuccess: () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'favorites' || q.queryKey[0] === 'favorite-schedule' }),
  });

  // Favourites carry ids only; name each from a matching session when one is listed.
  const nameOf = (targetId: string) => schedule.data?.find((s) => s.program_group_id === targetId || s.reservation_type_id === targetId)?.title;

  return (
    <Screen onRefresh={() => void Promise.all([favorites.refetch(), schedule.refetch()])} refreshing={favorites.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="favourites (GET /portal/favorites)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>Favourites for {clientName(actingFor)}</Heading>}
      {remove.error ? <ErrorBox error={remove.error} /> : null}
      {favorites.isLoading ? (
        <Loading />
      ) : favorites.error ? (
        <ErrorBox error={favorites.error} />
      ) : !favorites.data?.length ? (
        <Empty text="No favourites yet. Add programs or booking types as favourites on the web portal." />
      ) : (
        favorites.data.map((f) => (
          <Surface key={f.id}>
            <Body>{nameOf(f.target_id) ?? KIND_LABEL[f.kind] ?? 'Favourite'}</Body>
            <Small>{KIND_LABEL[f.kind] ?? f.kind}</Small>
            <Button compact variant="danger" label="Remove" loading={remove.isPending && remove.variables === f.id} onPress={() => remove.mutate(f.id)} />
          </Surface>
        ))
      )}
      <Heading>Next 14 days</Heading>
      {schedule.isLoading ? (
        <Loading />
      ) : schedule.error ? (
        <ErrorBox error={schedule.error} />
      ) : !schedule.data?.length ? (
        <Empty text="No upcoming sessions match your favourites." />
      ) : (
        schedule.data.map((s) => (
          <Surface key={s.session_id}>
            <Body>{s.title ?? 'Session'}</Body>
            <Small>{formatDateTime(s.starts_at, s.time_zone)}</Small>
            {s.is_bookable ? <Badge label="Open" tone="success" /> : s.can_join_waitlist ? <Badge label="Waitlist" tone="warning" /> : <Badge label="Not bookable" />}
          </Surface>
        ))
      )}
      <Small>Book from the Schedule tab.</Small>
    </Screen>
  );
}
