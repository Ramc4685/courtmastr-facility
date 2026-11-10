import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Switch } from 'react-native';

import { portal } from '../adapters';
import { api, unwrap } from '../api/client';
import { useApp } from '../lib/app-state';
import { biometricAvailable, biometricEnabled, setBiometricEnabled } from '../lib/biometric';
import { config } from '../lib/config';
import { registerForPush, type PushResult } from '../lib/push';
import { Body, Button, ErrorBox, Heading, Loading, Row, Screen, Small, Surface } from '../ui/kit';

/** Real data: GET /me and GET /auth/sessions; revoking another device is DELETE /auth/sessions/{id}. */
export default function Profile() {
  const { tenant, theme } = useApp();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me', tenant?.slug], queryFn: () => unwrap(api().GET('/api/v1/me')) });
  const sessions = useQuery({ queryKey: ['own-sessions', tenant?.slug], queryFn: () => unwrap(api().GET('/api/v1/auth/sessions')) });
  const revoke = useMutation({
    mutationFn: (id: string) => unwrap(api().DELETE('/api/v1/auth/sessions/{session_id}', { params: { path: { session_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['own-sessions'] }),
  });
  const [bio, setBio] = useState<{ available: boolean; enabled: boolean }>({ available: false, enabled: false });
  const [push, setPush] = useState<PushResult | null>(null);

  useEffect(() => {
    void Promise.all([biometricAvailable(), biometricEnabled()]).then(([available, enabled]) => setBio({ available, enabled }));
  }, []);

  const list = Array.isArray(sessions.data) ? sessions.data : [];

  return (
    <Screen onRefresh={() => void Promise.all([me.refetch(), sessions.refetch()])} refreshing={me.isRefetching}>
      <Surface>
        <Heading>Account</Heading>
        {me.isLoading ? <Loading /> : me.error ? <ErrorBox error={me.error} /> : (
          <>
            <Body>{me.data?.principal.display_name}</Body>
            <Small>{me.data?.principal.email}</Small>
            <Small>{me.data?.tenant.name}</Small>
          </>
        )}
      </Surface>
      <Surface>
        <Heading>Security</Heading>
        <Row
          title="Unlock with Face ID / Touch ID"
          subtitle={bio.available ? 'Locks your saved sign-in; your card stays available.' : 'Not set up on this phone.'}
          right={
            <Switch
              accessibilityLabel="Unlock with biometrics"
              value={bio.enabled}
              disabled={!bio.available}
              onValueChange={(enabled) => void setBiometricEnabled(enabled).then(() => setBio((b) => ({ ...b, enabled })))}
            />
          }
        />
        <Heading>Signed-in devices</Heading>
        {sessions.isLoading ? <Loading /> : sessions.error ? <ErrorBox error={sessions.error} /> : list.map((s) => (
          <Row
            key={s.id}
            title={`${s.kind === 'mobile' ? 'Phone' : 'Browser'}${s.is_current ? ' (this one)' : ''}`}
            subtitle={`Last seen ${s.last_seen_at ? new Date(s.last_seen_at).toLocaleDateString() : 'never'}`}
            right={s.is_current ? undefined : <Button compact variant="danger" label="Sign out" onPress={() => revoke.mutate(s.id)} loading={revoke.isPending && revoke.variables === s.id} />}
          />
        ))}
        {revoke.error ? <ErrorBox error={revoke.error} /> : null}
      </Surface>
      <Surface>
        <Heading>Notifications</Heading>
        <Button label="Turn on push notifications" variant="secondary" onPress={() => void registerForPush().then(setPush).catch((e) => setPush({ status: 'unsupported', reason: String(e) }))} />
        {push ? <Small muted={false}>{push.status === 'registered' ? `This phone is registered${portal.isDemo ? ' (demo registration, not sent to a server)' : ''}.` : push.reason}</Small> : null}
      </Surface>
      <Small>
        Version {config.appVersion} · data: {portal.isDemo ? 'demo adapter for portal features' : 'live API'} · theme: {theme.brand.source}
      </Small>
    </Screen>
  );
}
