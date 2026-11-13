import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';

import { portal } from '../adapters';
import { NotAvailable } from '../adapters/types';
import { ApiError } from '../api/errors';
import { useApp } from '../lib/app-state';
import { lookupTenant, normaliseSlug } from '../lib/tenant';
import { Body, Button, DemoBanner, Empty, ErrorBox, Field, Heading, Loading, Row, Screen, Small, Surface } from '../ui/kit';

export default function Facilities() {
  const { selectTenant, tenant } = useApp();
  const [q, setQ] = useState('');
  const [slug, setSlug] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const directory = useQuery({ queryKey: ['directory', q.trim()], queryFn: () => portal.searchDirectory(q), retry: false });

  async function open(input: string) {
    const normalised = normaliseSlug(input);
    if (!normalised) {
      setError(new ApiError({ status: 422, code: 'bad-slug', detail: 'Facility codes use lowercase letters, numbers and dashes.' }));
      return;
    }
    setBusy(normalised);
    setError(null);
    try {
      const { tenant: found } = await lookupTenant(normalised);
      await selectTenant(found);
      router.replace('/');
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'tenant-not-found' ? new ApiError({ ...e.problem, detail: 'No facility uses that code.' }) : e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen>
      <Body muted>Search by name or city, or enter the facility code from your welcome email.</Body>
      {tenant && <Small>Currently selected: {tenant.name}</Small>}
      <Field label="Search" value={q} onChangeText={setQ} placeholder="Name or city" autoCorrect={false} returnKeyType="search" />
      {portal.isDemo && <DemoBanner waitingOn="the facility directory (GET /public/app-directory)" />}
      <Surface>
        {directory.isLoading ? (
          <Loading />
        ) : directory.error instanceof NotAvailable ? (
          <Empty text="Search by name is not available yet. Enter the facility code below." />
        ) : directory.error ? (
          <ErrorBox error={directory.error} />
        ) : directory.data?.length ? (
          directory.data.map((entry) => (
            <Row
              key={entry.slug}
              title={entry.name}
              subtitle={[entry.city, busy === entry.slug ? 'Opening…' : null].filter(Boolean).join(' · ')}
              onPress={() => open(entry.slug)}
            />
          ))
        ) : (
          <Empty text={q.trim().length < 2 ? 'Type at least two letters of the facility name.' : 'No facilities match. Try the facility code instead.'} />
        )}
      </Surface>
      <Heading>Have a facility code?</Heading>
      <Field label="Facility code" value={slug} onChangeText={setSlug} placeholder="e.g. courtside-demo" autoCapitalize="none" autoCorrect={false} onSubmitEditing={() => open(slug)} />
      {error ? <ErrorBox error={error} /> : null}
      <Button label="Open facility" onPress={() => open(slug)} loading={!!busy && busy === normaliseSlug(slug)} disabled={!slug.trim()} />
      <Small>The facility is confirmed against its live public profile before you sign in.</Small>
    </Screen>
  );
}
