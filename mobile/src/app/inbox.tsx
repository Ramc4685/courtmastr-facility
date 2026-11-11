import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Linking } from 'react-native';

import { portal, type InboxItem } from '../adapters';
import { useApp } from '../lib/app-state';
import { useInbox } from '../lib/hooks';
import { Badge, Body, Button, DemoBanner, Empty, ErrorBox, Loading, Screen, Small, Surface } from '../ui/kit';

export default function Inbox() {
  const { tenant } = useApp();
  const inbox = useInbox();
  const qc = useQueryClient();
  const markRead = useMutation({
    mutationFn: (id: string) => portal.markInboxRead(id),
    // Read state is the server's (synced across devices); update the cache with what the server returned.
    onSuccess: (item) =>
      qc.setQueryData<InboxItem[]>(['inbox', tenant?.slug], (items) => items?.map((i) => (i.id === item.id ? item : i))),
  });

  const open = (item: InboxItem) => {
    if (!item.read_at) markRead.mutate(item.id);
    if (item.link_url?.startsWith('https://')) void Linking.openURL(item.link_url);
  };

  return (
    <Screen onRefresh={() => void inbox.refetch()} refreshing={inbox.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="the inbox API (GET /portal/inbox, POST /portal/inbox/{id}/read)" />}
      {markRead.error ? <ErrorBox error={markRead.error} /> : null}
      {inbox.isLoading ? <Loading /> : inbox.error ? <ErrorBox error={inbox.error} /> : !inbox.data?.length ? <Empty text="No notifications in the last 30 days." /> : inbox.data.map((item) => (
        <Surface key={item.id}>
          <Body>{item.title}</Body>
          {!item.read_at && <Badge label="Unread" tone="brand" />}
          <Small muted={false}>{item.body}</Small>
          <Small>{new Date(item.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</Small>
          {!item.read_at || item.link_url ? (
            <Button compact variant="secondary" label={item.link_url ? 'Open' : 'Mark as read'} onPress={() => open(item)} loading={markRead.isPending && markRead.variables === item.id} />
          ) : null}
        </Surface>
      ))}
      <Small>Messages stay here for 30 days, even with push notifications turned off.</Small>
    </Screen>
  );
}
