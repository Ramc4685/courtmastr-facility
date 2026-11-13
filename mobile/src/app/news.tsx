import { useQuery } from '@tanstack/react-query';
import { Linking } from 'react-native';

import { portal } from '../adapters';
import { useApp } from '../lib/app-state';
import { useHomeLocation } from '../lib/hooks';
import { formatDate } from '../ui/format';
import { Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';

const KINDS: [kind: string, label: string][] = [
  ['announcement', 'Announcements'],
  ['news', 'News'],
  ['promotion', 'Promotions'],
  ['gallery', 'Gallery'],
  ['info_page', 'Information'],
];

/** APP-07 news and info pages, APP-14 announcements, promotions and gallery. Plain text and https links only. */
export default function News() {
  const { tenant } = useApp();
  const locationId = useHomeLocation()?.id;
  const items = useQuery({ queryKey: ['app-contents', tenant?.slug, locationId], queryFn: () => portal.listAppContents(locationId) });
  const data = items.data ?? [];

  return (
    <Screen onRefresh={() => void items.refetch()} refreshing={items.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="member app content (GET /portal/app-contents)" />}
      {items.isLoading ? (
        <Loading />
      ) : items.error ? (
        <ErrorBox error={items.error} />
      ) : !data.length ? (
        <Empty text="Nothing posted yet." />
      ) : (
        KINDS.map(([kind, label]) => {
          const group = data.filter((i) => i.kind === kind);
          return group.length ? [
            <Heading key={kind}>{label}</Heading>,
            ...group.map((item) => (
              <Surface key={item.id}>
                <Body>{item.title}</Body>
                <Small>{formatDate(item.publish_at)}</Small>
                <Small muted={false}>{item.body_text}</Small>
                {item.link_url?.startsWith('https://') ? (
                  <Button compact variant="secondary" label="Open link" onPress={() => void Linking.openURL(item.link_url!)} />
                ) : null}
              </Surface>
            )),
          ] : null;
        })
      )}
      {/* shortcut: images need an authenticated image loader the app does not have yet; add one to show them. */}
      {data.some((i) => i.has_image) && <Small>Pictures are not shown in the app yet.</Small>}
    </Screen>
  );
}
