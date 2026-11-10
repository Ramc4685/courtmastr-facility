// Landing for <scheme>://auth/magic-link#token=... (or the tenant's universal link). The token rides in the
// fragment, which the router does not keep in its route state; we read it once from the raw URL, consume it
// with a POST, and replace this screen so it is not left in navigation history (security-baseline 17.2).
import * as Linking from 'expo-linking';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';

import { useApp } from '../../lib/app-state';
import { extractLinkToken } from '../../lib/auth';
import { Button, ErrorBox, Loading, Screen } from '../../ui/kit';

export default function MagicLinkLanding() {
  const url = Linking.useLinkingURL();
  const { consumeMagicLink } = useApp();
  const [failure, setFailure] = useState<unknown>(null);
  const done = useRef(false);
  const token = url ? extractLinkToken(url) : null;
  const error = failure ?? (url && !token ? new Error('This sign-in link is incomplete.') : null);

  useEffect(() => {
    if (!token || done.current) return;
    done.current = true;
    consumeMagicLink(token)
      .then(() => router.replace('/'))
      .catch(setFailure);
  }, [token, consumeMagicLink]);

  return (
    <Screen>
      {error ? (
        <>
          <ErrorBox error={error} />
          <Button label="Back to sign in" onPress={() => router.replace('/sign-in')} />
        </>
      ) : (
        <Loading />
      )}
    </Screen>
  );
}
