// Deep link / QR entry: <scheme>://t/<tenant-slug>. Confirms the tenant against the real API, then signs in.
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';

import { useApp } from '../../lib/app-state';
import { lookupTenant, normaliseSlug } from '../../lib/tenant';
import { Button, ErrorBox, Loading, Screen } from '../../ui/kit';

export default function TenantLink() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { selectTenant, status } = useApp();
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const normalised = normaliseSlug(String(slug ?? ''));
    if (!normalised || status === 'loading') return;
    lookupTenant(normalised)
      .then(({ tenant }) => selectTenant(tenant))
      .then(() => router.replace('/'))
      .catch(setError);
  }, [slug, status, selectTenant]);

  return (
    <Screen>
      {error ? (
        <>
          <ErrorBox error={error} />
          <Button label="Search facilities" onPress={() => router.replace('/facilities')} />
        </>
      ) : (
        <Loading />
      )}
    </Screen>
  );
}
