import { useQuery } from '@tanstack/react-query';

import { portal, type ClientPackage, type MembershipContract } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { formatDate, formatMoney } from '../ui/format';
import { Badge, Body, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

const statusTone = (s: MembershipContract['status'] | ClientPackage['status']) =>
  s === 'active' ? 'success' : s === 'frozen' || s === 'upcoming' ? 'warning' : 'neutral';

export default function Memberships() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const clientId = actingFor?.client.id;
  const contracts = useQuery({ queryKey: ['memberships', tenant?.slug, clientId], queryFn: () => portal.listMemberships(clientId!), enabled: !!clientId });
  const packages = useQuery({ queryKey: ['packages', tenant?.slug, clientId], queryFn: () => portal.listPackages(clientId!), enabled: !!clientId });

  return (
    <Screen onRefresh={() => void Promise.all([contracts.refetch(), packages.refetch()])} refreshing={contracts.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="memberships and packages (GET /portal/membership-contracts, /portal/client-packages)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>{clientName(actingFor)}</Heading>}
      <Heading>Memberships</Heading>
      {contracts.isLoading ? <Loading /> : contracts.error ? <ErrorBox error={contracts.error} /> : !contracts.data?.length ? <Empty text="No memberships." /> : contracts.data.map((m) => (
        <Surface key={m.id}>
          <Body>{m.name}</Body>
          <Badge label={m.status} tone={statusTone(m.status)} />
          <Small>
            {formatMoney(m.term_fee_minor)} every {m.billing_interval_count > 1 ? `${m.billing_interval_count} ` : ''}{m.billing_interval_unit}
            {m.is_autopay ? ' · autopay' : ''}
          </Small>
          <Small>
            {formatDate(m.start_on)} – {formatDate(m.end_on)}
            {m.is_auto_renew && m.renew_on ? ` · renews ${formatDate(m.renew_on)}` : ''}
          </Small>
          {m.max_visits_count !== null && <Small>{m.max_visits_count - m.visits_used_count} of {m.max_visits_count} visits left</Small>}
        </Surface>
      ))}
      <Heading>Packages</Heading>
      {packages.isLoading ? <Loading /> : packages.error ? <ErrorBox error={packages.error} /> : !packages.data?.length ? <Empty text="No packages." /> : packages.data.map((p) => (
        <Surface key={p.id}>
          <Body>{p.name}</Body>
          <Badge label={p.status} tone={statusTone(p.status)} />
          <Small>{p.is_unlimited ? 'Unlimited sessions' : `${p.sessions_available_count ?? 0} of ${p.sessions_granted_count} sessions left`}</Small>
          {p.valid_during[1] ? <Small>Valid until {formatDate(p.valid_during[1])}</Small> : null}
        </Surface>
      ))}
      <Small>Buying memberships and packages in the app arrives with the payment sheet (APP-19).</Small>
    </Screen>
  );
}
