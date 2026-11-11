// Landing for <scheme>://auth/magic-link#token=... (or the tenant's universal link). The token rides in the
// fragment, which the router does not keep in its route state; we read it once from the raw URL, consume it
// with a POST, and replace this screen so it is not left in navigation history (security-baseline 17.2).
// Login CSRF: a link this device did not ask for (in the last 20 minutes) is only used after the person
// confirms, so a link someone else sent cannot silently sign this phone into their account.
import * as Linking from 'expo-linking';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useApp } from '../../lib/app-state';
import { extractLinkToken } from '../../lib/auth';
import { Body, Button, ErrorBox, Heading, Loading, Screen, Surface } from '../../ui/kit';

export default function MagicLinkLanding() {
  const url = Linking.useLinkingURL();
  const { consumeMagicLink, magicLinkExpected, tenant } = useApp();
  const [failure, setFailure] = useState<unknown>(null);
  const [needsConfirm, setNeedsConfirm] = useState(false);
  const done = useRef(false);
  const token = url ? extractLinkToken(url) : null;
  const error = failure ?? (url && !token ? new Error('This sign-in link is incomplete.') : null);

  const consume = useCallback(
    (value: string) => {
      done.current = true;
      setNeedsConfirm(false);
      consumeMagicLink(value)
        .then(() => router.replace('/'))
        .catch(setFailure);
    },
    [consumeMagicLink],
  );

  useEffect(() => {
    if (!token || done.current) return;
    let live = true;
    magicLinkExpected().then((expected) => {
      if (!live || done.current) return;
      if (expected) consume(token);
      else setNeedsConfirm(true);
    });
    return () => {
      live = false;
    };
  }, [token, magicLinkExpected, consume]);

  return (
    <Screen>
      {error ? (
        <>
          <ErrorBox error={error} />
          <Button label="Back to sign in" onPress={() => router.replace('/sign-in')} />
        </>
      ) : needsConfirm && token ? (
        <Surface>
          <Heading>Sign in to {tenant?.name ?? 'this facility'}?</Heading>
          <Body>This phone did not ask for a sign-in link recently. Only continue if you requested this link yourself.</Body>
          <Button label="Continue" onPress={() => consume(token)} />
          <Button variant="secondary" label="Cancel" onPress={() => router.replace('/sign-in')} />
        </Surface>
      ) : (
        <Loading />
      )}
    </Screen>
  );
}
