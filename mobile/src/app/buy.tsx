// APP-19: buy a membership or package in the app with a new card. The server ends every sale in
// secure_online_checkout: nothing is sold unless the payment goes through, so a card that needs the bank's
// check is refused here (finish such a purchase on the web portal); invoice payments complete that check
// in the app (invoices.tsx).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { portal, type PlanOffer } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { useLocations } from '../lib/hooks';
import { formatMoney } from '../ui/format';
import { Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Row, Screen, Small, Surface } from '../ui/kit';
import { NewCard, useAttemptKey } from '../ui/NewCard';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

export default function Buy() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const qc = useQueryClient();
  const locations = useLocations().data ?? [];
  const locationId = actingFor?.client.home_location_id ?? locations[0]?.id ?? null;
  const offers = useQuery({ queryKey: ['offers', tenant?.slug, locationId], queryFn: () => portal.listOffers(locationId!), enabled: !!locationId });
  const [offer, setOffer] = useState<PlanOffer | null>(null);
  const [token, setToken] = useState('');
  const attempt = useAttemptKey();
  const buy = useMutation({
    mutationFn: () => portal.buy({ offer: offer!, clientId: actingFor!.client.id, locationId: locationId!, methodToken: token, idempotencyKey: attempt.key }),
    onSettled: (_sale, error) => attempt.settle(error),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memberships'] });
      void qc.invalidateQueries({ queryKey: ['packages'] });
    },
  });

  return (
    <Screen>
      {portal.isDemo && <DemoBanner waitingOn="online sales (POST /portal/client-packages, /portal/membership-contracts)" />}
      <ProfileSwitcher />
      {actingFor && <Small>Buying for {clientName(actingFor)}. Payment always uses your own card.</Small>}
      <Heading>Choose</Heading>
      {offers.isLoading ? <Loading /> : offers.error ? <ErrorBox error={offers.error} /> : !offers.data?.length ? <Empty text="Nothing is for sale online right now." /> : offers.data.map((o) => (
        <Row
          key={`${o.kind}-${o.id}`}
          title={o.name}
          subtitle={[o.kind === 'membership' ? 'Membership' : 'Package', o.price_minor !== null ? formatMoney(o.price_minor) : null, o.detail, offer?.id === o.id ? 'Selected' : null].filter(Boolean).join(' · ')}
          onPress={() => {
            setOffer(o);
            buy.reset();
          }}
        />
      ))}
      {offer && (
        <>
          <Heading>Pay with a new card</Heading>
          <NewCard value={token} onChange={setToken} />
          {buy.error ? <ErrorBox error={buy.error} /> : null}
          {buy.data ? (
            <Surface>
              <Body>{buy.data.payment_status === 'succeeded' || !buy.data.payment_status ? `${buy.data.name} is yours.` : `Payment is ${buy.data.payment_status.replace(/_/g, ' ')}; nothing is confirmed until it succeeds.`}</Body>
            </Surface>
          ) : (
            <Button label={`Buy ${offer.name}`} onPress={() => buy.mutate()} loading={buy.isPending} disabled={!token || !actingFor || !locationId} />
          )}
        </>
      )}
    </Screen>
  );
}
