// APP-06 / CHK-13: a wallet pass, a long-lived credential of its own that staff and the member can revoke and
// the door accepts. The pass file comes from the server's wallet-pass port; until issuer certificates exist it
// is an unsigned development pass, so the app says it is not ready for a phone wallet yet.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import * as Device from 'expo-device';
import { Alert } from 'react-native';

import { portal } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { useZone } from '../lib/hooks';
import { formatDateTime } from '../ui/format';
import { Body, Button, DemoBanner, Empty, ErrorBox, Loading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

export default function Wallet() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const qc = useQueryClient();
  const clientId = actingFor?.client.id;
  const passes = useQuery({ queryKey: ['wallet-passes', tenant?.slug], queryFn: () => portal.listWalletPasses() });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['wallet-passes'] });
  const issue = useMutation({
    mutationFn: () => portal.issueWalletPass({ clientId: clientId!, deviceLabel: Device.modelName ?? 'Phone', idempotencyKey: Crypto.randomUUID() }),
    onSuccess: refresh,
  });
  const revoke = useMutation({ mutationFn: (id: string) => portal.revokeWalletPass(id), onSuccess: refresh });
  const zone = useZone();
  const mine = passes.data?.filter((p) => p.client_id === clientId) ?? [];

  const confirmRevoke = (id: string) =>
    Alert.alert('Remove this pass?', 'It stops opening the door at once. You can add a new one later.', [
      { text: 'Keep it', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => revoke.mutate(id) },
    ]);

  return (
    <Screen onRefresh={() => void passes.refetch()} refreshing={passes.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="wallet passes (POST /portal/wallet-passes)" />}
      <ProfileSwitcher />
      {actingFor && <Small>Pass for {clientName(actingFor)}</Small>}
      {(issue.error || revoke.error) && <ErrorBox error={issue.error ?? revoke.error} />}
      {issue.data && !issue.data.is_signed && (
        <Surface>
          <Body>Pass created. It is a development pass (not signed), so phone wallets will not accept it yet.</Body>
        </Surface>
      )}
      {passes.isLoading ? (
        <Loading />
      ) : passes.error ? (
        <ErrorBox error={passes.error} />
      ) : !mine.length ? (
        <Empty text="No wallet pass yet." />
      ) : (
        mine.map((p) => (
          <Surface key={p.credential_id}>
            <Body>{p.device_label ?? 'Wallet pass'}</Body>
            <Small>Added {formatDateTime(p.issued_at, zone)}</Small>
            <Button compact variant="danger" label="Remove pass" onPress={() => confirmRevoke(p.credential_id)} loading={revoke.isPending && revoke.variables === p.credential_id} />
          </Surface>
        ))
      )}
      <Button label={mine.length ? 'Replace pass' : 'Add to wallet'} onPress={() => issue.mutate()} loading={issue.isPending} disabled={!clientId} />
      <Small>One pass per person: a new one replaces the old.</Small>
    </Screen>
  );
}
