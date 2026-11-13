import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Linking } from 'react-native';

import { portal, type LocationContact } from '../adapters';
import { useApp } from '../lib/app-state';
import { useHomeLocation, useLocations } from '../lib/hooks';
import { Body, Button, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { LocationPicker } from '../ui/LocationPicker';

const GROUPS: [kind: string, label: string][] = [
  ['department', 'Departments'],
  ['service', 'Services'],
];

/** APP-08 departments and APP-09 service contacts: public, so it works signed out too. */
export default function Contacts() {
  const { tenant } = useApp();
  const locations = useLocations();
  const home = useHomeLocation();
  const [picked, setPicked] = useState<string>();
  const locationId = picked ?? home?.id;
  const contacts = useQuery({
    queryKey: ['location-contacts', tenant?.slug, locationId],
    queryFn: () => portal.listLocationContacts(locationId!),
    enabled: !!locationId,
  });

  const card = (c: LocationContact) => (
    <Surface key={c.id}>
      <Body>{c.name}</Body>
      {c.role ? <Small>{c.role}</Small> : null}
      {c.phone ? <Button compact variant="secondary" label={`Call ${c.phone}`} onPress={() => void Linking.openURL(`tel:${c.phone!.replace(/[^\d+]/g, '')}`)} /> : null}
      {c.email ? <Button compact variant="secondary" label={`Email ${c.email}`} onPress={() => void Linking.openURL(`mailto:${c.email}`)} /> : null}
    </Surface>
  );

  return (
    <Screen onRefresh={() => void contacts.refetch()} refreshing={contacts.isRefetching}>
      <LocationPicker locations={locations.data ?? []} value={locationId} onChange={setPicked} />
      {locations.isLoading || contacts.isLoading ? (
        <Loading />
      ) : contacts.error ? (
        <ErrorBox error={contacts.error} />
      ) : !contacts.data?.length ? (
        <Empty text="No contacts published for this location." />
      ) : (
        GROUPS.map(([kind, label]) => {
          const group = contacts.data.filter((c) => c.kind === kind);
          return group.length ? [<Heading key={kind}>{label}</Heading>, ...group.map(card)] : null;
        })
      )}
    </Screen>
  );
}
