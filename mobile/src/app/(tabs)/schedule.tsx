import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';

import { portal, type SessionListing } from '../../adapters';
import { useApp } from '../../lib/app-state';
import { useBookingActions } from '../../lib/booking';
import { clientName, useHousehold } from '../../lib/household';
import { useZone } from '../../lib/hooks';
import { formatDay, formatTime } from '../../ui/format';
import { Badge, Button, DemoBanner, Empty, ErrorBox, Loading, Screen, Small, Surface } from '../../ui/kit';
import { ProfileSwitcher } from '../../ui/ProfileSwitcher';

const DAY = 86_400_000;

const ELIGIBILITY: Record<SessionListing['eligibility'], { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' | 'brand' }> = {
  bookable: { label: 'Open', tone: 'success' },
  already_booked: { label: 'Booked', tone: 'brand' },
  needs_purchase: { label: 'Needs a package', tone: 'warning' },
  full_waitlist: { label: 'Waitlist', tone: 'warning' },
  full: { label: 'Full', tone: 'danger' },
  closed: { label: 'Closed', tone: 'neutral' },
  not_yet_open: { label: 'Opens later', tone: 'neutral' },
};

export default function Schedule() {
  const { tenant, theme: t } = useApp();
  const { actingFor } = useHousehold();
  const zone = useZone();
  const clientId = actingFor?.client.id;
  const days = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return Array.from({ length: 7 }, (_, i) => new Date(start.getTime() + i * DAY));
  }, []);
  const [dayIndex, setDayIndex] = useState(0);
  const from = days[dayIndex]!;
  const to = new Date(from.getTime() + DAY);
  const listings = useQuery({
    queryKey: ['sessions', tenant?.slug, clientId, from.toISOString()],
    queryFn: () => portal.listSessionListings({ clientId: clientId!, from: new Date(Math.max(from.getTime(), Date.now())).toISOString(), to: to.toISOString() }),
    enabled: !!clientId,
  });
  const { book, cancel } = useBookingActions(clientId);

  const confirmCancel = (s: SessionListing) =>
    Alert.alert('Cancel booking?', `${s.name} at ${formatTime(s.starts_at, zone)}`, [
      { text: 'Keep it', style: 'cancel' },
      { text: 'Cancel booking', style: 'destructive', onPress: () => cancel.mutate(s.my_enrollment_id!) },
    ]);

  return (
    <Screen onRefresh={() => void listings.refetch()} refreshing={listings.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="session listings and enrollments (GET /portal/session-listings, POST /portal/enrollments)" />}
      <ProfileSwitcher />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: t.space(2) }} accessibilityRole="tablist">
        {days.map((d, i) => {
          const selected = i === dayIndex;
          return (
            <Pressable
              key={d.toISOString()}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              accessibilityLabel={formatDay(d.toISOString(), zone)}
              onPress={() => setDayIndex(i)}
              style={{ minWidth: 56, minHeight: 56, borderRadius: t.radius.md, alignItems: 'center', justifyContent: 'center', backgroundColor: selected ? t.colors.primary : t.colors.surface, borderWidth: 1, borderColor: selected ? t.colors.primary : t.colors.border }}
            >
              <Text style={{ color: selected ? t.colors.onPrimary : t.colors.textMuted, fontSize: t.font.small }}>
                {new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(d)}
              </Text>
              <Text style={{ color: selected ? t.colors.onPrimary : t.colors.text, fontSize: t.font.heading, fontWeight: '700' }}>{d.getDate()}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {actingFor && <Small>Booking for {clientName(actingFor)} · times in {zone.replace('_', ' ')}</Small>}
      {(book.error || cancel.error) && <ErrorBox error={book.error ?? cancel.error} />}
      {listings.isLoading ? (
        <Loading />
      ) : listings.error ? (
        <ErrorBox error={listings.error} />
      ) : !listings.data?.length ? (
        <Empty text="No sessions left on this day." />
      ) : (
        listings.data.map((s) => {
          const e = ELIGIBILITY[s.eligibility];
          return (
            <Surface key={s.session_id}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: t.space(2) }}>
                <Text style={{ color: t.colors.text, fontWeight: '600', fontSize: t.font.body, flex: 1 }}>{s.name}</Text>
                <Badge label={e.label} tone={e.tone} />
              </View>
              <Small>
                {formatTime(s.starts_at, zone)}–{formatTime(s.ends_at, zone)}
                {s.resource_name ? ` · ${s.resource_name}` : ''}
                {s.trainer_name ? ` · ${s.trainer_name}` : ''}
                {s.spots_left !== null ? ` · ${s.spots_left} spot${s.spots_left === 1 ? '' : 's'} left` : ''}
              </Small>
              {s.eligibility === 'bookable' && (
                <Button compact label="Book" onPress={() => book.mutate(s.session_id)} loading={book.isPending && book.variables === s.session_id} />
              )}
              {s.my_enrollment_id && (
                <Button compact variant="danger" label="Cancel booking" onPress={() => confirmCancel(s)} loading={cancel.isPending && cancel.variables === s.my_enrollment_id} />
              )}
            </Surface>
          );
        })
      )}
    </Screen>
  );
}
