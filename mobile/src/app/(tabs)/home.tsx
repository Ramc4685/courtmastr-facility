import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { portal } from '../../adapters';
import { useApp } from '../../lib/app-state';
import { clientName, useHousehold } from '../../lib/household';
import { useAppConfig, useBookings, useInbox, useZone } from '../../lib/hooks';
import { resolveTiles } from '../../lib/tiles';
import { formatDateTime } from '../../ui/format';
import { Body, DemoBanner, Heading, Loading, Screen, Small, Surface, Title } from '../../ui/kit';
import { ProfileSwitcher } from '../../ui/ProfileSwitcher';

export default function Home() {
  const { tenant, principal, theme: t } = useApp();
  const { actingFor, isLoading } = useHousehold();
  const bookings = useBookings();
  const inbox = useInbox();
  const zone = useZone();
  const { tiles, design } = resolveTiles(useAppConfig().data);
  const radius = design.corners === 'square' ? t.radius.sm : t.radius.lg;
  const next = bookings.data?.[0];
  const unread = inbox.data?.filter((i) => !i.read_at).length ?? 0;

  return (
    <Screen onRefresh={() => void Promise.all([bookings.refetch(), inbox.refetch()])} refreshing={bookings.isRefetching}>
      <Title>{tenant?.name}</Title>
      <Body muted>Signed in as {principal?.email}</Body>
      {portal.isDemo && <DemoBanner waitingOn="household, booking and inbox APIs (portal clients, enrollments, inbox)" />}
      <Heading>Acting for</Heading>
      {isLoading ? <Loading /> : <ProfileSwitcher />}
      {actingFor && <Small>Bookings and purchases below are for {clientName(actingFor)}. Payment always uses your own account.</Small>}
      <Surface>
        <Heading>Next booking</Heading>
        {next ? (
          <Body>
            {next.session.name} · {formatDateTime(next.session.starts_at, zone)}
          </Body>
        ) : (
          <Body muted>Nothing booked yet.</Body>
        )}
        {unread > 0 && <Small muted={false}>{unread} unread notification{unread > 1 ? 's' : ''}</Small>}
      </Surface>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.space(3) }}>
        {tiles.map((tile) => (
          <Pressable
            key={tile.key}
            accessibilityRole="button"
            accessibilityLabel={tile.caption}
            onPress={() => router.push(tile.href)}
            style={({ pressed }) => ({
              width: design.columns === 1 || tile.large ? '100%' : '47%',
              minHeight: tile.large ? 96 : 72,
              borderRadius: radius,
              backgroundColor: t.colors.surface,
              borderWidth: 1,
              borderColor: t.colors.border,
              padding: t.space(4),
              justifyContent: 'flex-end',
              opacity: pressed ? 0.75 : 1,
            })}
          >
            <View style={{ width: 24, height: 4, borderRadius: 2, backgroundColor: t.colors.accent, marginBottom: t.space(2) }} />
            <Text style={{ color: t.colors.text, fontWeight: '600', fontSize: t.font.body }}>{tile.caption}</Text>
          </Pressable>
        ))}
      </View>
    </Screen>
  );
}
