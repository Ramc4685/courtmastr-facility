import { router } from 'expo-router';
import { Linking } from 'react-native';

import type { FacilityHoursDay } from '../api/types';
import { useApp } from '../lib/app-state';
import { useLocations } from '../lib/hooks';
import { Body, Button, Empty, ErrorBox, Heading, Loading, Row, Screen, Small, Surface, Title } from '../ui/kit';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const hoursText = (d: FacilityHoursDay) => (d.is_closed ? 'Closed' : `${d.opens_time ?? '?'}–${d.closes_time ?? '?'}`);

/** Real data: GET /public/locations (name, contact, weekly hours in the location's own time zone). */
export default function Facility() {
  const { tenant, theme } = useApp();
  const locations = useLocations();
  return (
    <Screen onRefresh={() => void locations.refetch()} refreshing={locations.isRefetching}>
      <Title>{tenant?.name}</Title>
      {locations.isLoading ? <Loading /> : locations.error ? <ErrorBox error={locations.error} /> : !locations.data?.length ? <Empty text="No public locations." /> : locations.data.map((loc) => (
        <Surface key={loc.id}>
          <Heading>{loc.public_name}</Heading>
          <Small>{[loc.city, loc.region].filter(Boolean).join(', ')} · {loc.time_zone.replace('_', ' ')}</Small>
          {loc.phone ? <Row title="Call" subtitle={loc.phone} onPress={() => void Linking.openURL(`tel:${loc.phone}`)} /> : null}
          {loc.email ? <Row title="Email" subtitle={loc.email} onPress={() => void Linking.openURL(`mailto:${loc.email}`)} /> : null}
          {loc.facility_hours.length ? (
            [...loc.facility_hours].sort((a, b) => a.weekday - b.weekday).map((d) => (
              <Row key={d.weekday} title={WEEKDAYS[d.weekday - 1] ?? String(d.weekday)} right={<Body muted={d.is_closed}>{hoursText(d)}</Body>} />
            ))
          ) : (
            <Small>Hours not published.</Small>
          )}
        </Surface>
      ))}
      <Small>Theme: {theme.brand.source === 'tenant' ? 'from the facility' : theme.brand.source === 'cached' ? 'saved from the facility' : theme.brand.source === 'demo' ? 'demo colours for this sample facility' : 'bundled (the facility colours could not be loaded)'}.</Small>
      <Button label="Switch facility" variant="secondary" onPress={() => router.push('/facilities')} />
    </Screen>
  );
}
