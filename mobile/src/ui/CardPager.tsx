import { useEffect, useState } from 'react';
import { AppState, FlatList, useWindowDimensions, View } from 'react-native';

import { portal } from '../adapters';
import { useApp } from '../lib/app-state';
import { installationId, loadCards, syncCards, type StoredCards } from '../lib/card';
import { useHousehold } from '../lib/household';
import { useOnline } from '../lib/query';
import { Empty, ErrorBox, Small } from './kit';
import { MemberCard } from './MemberCard';

/** Local storage first, network second: the cards render before (and without) any request. */
export function useCards() {
  const { tenant, status } = useApp();
  const { members } = useHousehold();
  const online = useOnline();
  const slug = tenant?.slug;
  const [stored, setStored] = useState<StoredCards | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [syncTick, setSyncTick] = useState(0);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (slug) void loadCards(slug).then(setStored);
  }, [slug]);

  useEffect(() => {
    if (!slug || status !== 'signedIn' || !online || members.length === 0) return;
    let live = true;
    installationId()
      .then((inst) => syncCards(slug, members, (clientId) => portal.issueAppCard(clientId, inst)))
      .then((next) => {
        if (!live) return;
        setStored(next);
        setError(null);
      })
      .catch((e: unknown) => live && setError(e));
    return () => {
      live = false;
    };
  }, [slug, status, online, members, syncTick]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => {
      if (s !== 'active') return;
      setNow(Date.now());
      setSyncTick((n) => n + 1);
    });
    const tick = setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      sub.remove();
      clearInterval(tick);
    };
  }, []);

  return { stored, now, online, error };
}

/** Every card the identity can act for, swipeable, regardless of the selected profile (ADR 0006 s5). */
export function CardPager() {
  const { tenant } = useApp();
  const { stored, now, online, error } = useCards();
  const { width } = useWindowDimensions();
  const cardWidth = width - 32;
  if (!stored) return null;
  if (stored.display.length === 0) {
    return <Empty text={online ? 'Loading your cards…' : 'Your cards appear here after you have been online once.'} />;
  }
  return (
    <View style={{ gap: 12 }}>
      <FlatList
        horizontal
        pagingEnabled
        snapToInterval={cardWidth + 12}
        decelerationRate="fast"
        showsHorizontalScrollIndicator={false}
        data={stored.display}
        keyExtractor={(d) => d.clientId}
        ItemSeparatorComponent={() => <View style={{ width: 12 }} />}
        renderItem={({ item }) => (
          <MemberCard display={item} token={stored.tokens[item.clientId]} tenantName={tenant?.name ?? ''} now={now} online={online} demo={portal.isDemo} width={cardWidth} />
        )}
      />
      {stored.display.length > 1 ? <Small>Swipe for {stored.display.length - 1} more family card(s).</Small> : null}
      {error && online ? <ErrorBox error={error} /> : null}
    </View>
  );
}
