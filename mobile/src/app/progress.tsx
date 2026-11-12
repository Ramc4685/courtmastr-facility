import { useQuery } from '@tanstack/react-query';

import { portal } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { formatDate } from '../ui/format';
import { Body, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

// Values arrive as decimal strings ("81.500000"); show them without trailing zeros.
const num = (v: string) => String(Number(v));

export default function Progress() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const clientId = actingFor?.client.id;
  const bests = useQuery({ queryKey: ['progress', tenant?.slug, clientId], queryFn: () => portal.listProgress(clientId!), enabled: !!clientId });

  return (
    <Screen onRefresh={() => void bests.refetch()} refreshing={bests.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="assessment results (GET /portal/assessment-bests)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>{clientName(actingFor)}</Heading>}
      {bests.isLoading ? (
        <Loading />
      ) : bests.error ? (
        <ErrorBox error={bests.error} />
      ) : !bests.data?.length ? (
        <Empty text="No assessment results yet." />
      ) : (
        bests.data.map((b) => (
          <Surface key={b.assessment_field_id}>
            <Body>{b.field_name}</Body>
            <Small>
              Latest {num(b.latest_value)} {b.unit_label ?? ''} · {formatDate(b.latest_recorded_at)}
            </Small>
            {b.best_value !== null && b.better_direction !== 'none' && (
              <Small>
                Best {num(b.best_value)} {b.unit_label ?? ''}
                {b.best_recorded_at ? ` · ${formatDate(b.best_recorded_at)}` : ''}
              </Small>
            )}
            <Small>{b.template_name}</Small>
          </Surface>
        ))
      )}
    </Screen>
  );
}
