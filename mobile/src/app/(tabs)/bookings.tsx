import { Alert, Share } from 'react-native';

import { portal } from '../../adapters';
import { useBookingActions } from '../../lib/booking';
import { clientName, useHousehold } from '../../lib/household';
import { useBookings, useZone } from '../../lib/hooks';
import { formatDateTime } from '../../ui/format';
import { Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../../ui/kit';
import { ProfileSwitcher } from '../../ui/ProfileSwitcher';

export default function MyBookings() {
  const { actingFor } = useHousehold();
  const bookings = useBookings();
  const zone = useZone();
  const { cancel } = useBookingActions(actingFor?.client.id);

  return (
    <Screen onRefresh={() => void bookings.refetch()} refreshing={bookings.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="enrollments (GET /portal/enrollments)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>Upcoming for {clientName(actingFor)}</Heading>}
      {cancel.error ? <ErrorBox error={cancel.error} /> : null}
      {bookings.isLoading ? (
        <Loading />
      ) : bookings.error ? (
        <ErrorBox error={bookings.error} />
      ) : !bookings.data?.length ? (
        <Empty text="No upcoming bookings. Book from the Schedule tab." />
      ) : (
        bookings.data.map(({ enrollment, session }) => (
          <Surface key={enrollment.id}>
            <Body>{session.name}</Body>
            <Small>
              {formatDateTime(session.starts_at, zone)}
              {session.resource_name ? ` · ${session.resource_name}` : ''}
            </Small>
            <Button
              compact
              variant="secondary"
              label="Share"
              onPress={() => void Share.share({ title: session.name, message: `${session.name}\n${formatDateTime(session.starts_at, zone)}` })}
            />
            <Button
              compact
              variant="danger"
              label="Cancel booking"
              loading={cancel.isPending && cancel.variables === enrollment.id}
              onPress={() =>
                Alert.alert('Cancel booking?', session.name, [
                  { text: 'Keep it', style: 'cancel' },
                  { text: 'Cancel booking', style: 'destructive', onPress: () => cancel.mutate(enrollment.id) },
                ])
              }
            />
          </Surface>
        ))
      )}
      <Small>Bookings saved on this phone stay visible offline. Cancelling needs a connection.</Small>
    </Screen>
  );
}
