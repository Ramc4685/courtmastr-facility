import { router } from 'expo-router';
import { Share } from 'react-native';

import { useApp } from '../../lib/app-state';
import { shareUrl } from '../../lib/config';
import { useInbox } from '../../lib/hooks';
import { Button, Row, Screen, Small, Surface } from '../../ui/kit';

export default function More() {
  const { signOut, tenant } = useApp();
  const inbox = useInbox();
  const unread = inbox.data?.filter((i) => !i.read_at).length ?? 0;
  const link = tenant ? shareUrl(tenant.slug) : null;
  return (
    <Screen>
      <Surface>
        <Row title="Memberships & packages" onPress={() => router.push('/memberships')} />
        <Row title="Progress" subtitle="Assessment results" onPress={() => router.push('/progress')} />
        <Row title="Invoices & payments" onPress={() => router.push('/invoices')} />
        <Row title="Notifications" subtitle={unread ? `${unread} unread` : undefined} onPress={() => router.push('/inbox')} />
        <Row title="News & info" onPress={() => router.push('/news')} />
        <Row title="Favourites" subtitle="Your programs and next sessions" onPress={() => router.push('/favorites')} />
        <Row title="Facility info" subtitle={tenant?.name} onPress={() => router.push('/facility')} />
        <Row title="Contacts" onPress={() => router.push('/contacts')} />
        <Row title="Send feedback" onPress={() => router.push('/feedback')} />
        {link && tenant ? <Row title="Tell a friend" onPress={() => void Share.share({ message: `Come and try ${tenant.name}: ${link}` })} /> : null}
        <Row title="Profile & security" onPress={() => router.push('/profile')} />
      </Surface>
      <Button label="Sign out" variant="danger" onPress={() => void signOut().then(() => router.replace('/'))} />
      <Small>Signing out removes this phone&apos;s cards and saved data for {tenant?.name}.</Small>
    </Screen>
  );
}
