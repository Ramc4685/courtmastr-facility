// New-card entry for in-app purchases (APP-19). Card data only ever lives in the processor's own component:
// the fake processor (development) offers scripted test methods and nobody types a number; a real processor
// needs its native payment sheet, which this build does not bundle, so the app says so instead of collecting
// card details itself. Mirrors web/src/features/billing/PaymentMethodField.tsx.
import { useQuery } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import { useCallback, useState } from 'react';

import { portal } from '../adapters';
import { ApiError } from '../api/errors';
import { useApp } from '../lib/app-state';
import { Body, ErrorBox, Loading, Row, Small, Surface } from './kit';

const FAKE_CARDS = [
  { token: 'tok_card_ok', label: 'Test card: approved (Visa 4242)' },
  { token: 'tok_card_declined', label: 'Test card: declined' },
  { token: 'tok_card_auth', label: 'Test card: needs authentication' },
  { token: 'tok_card_unknown', label: 'Test card: processor times out' },
];

/** Whether a failed purchase's outcome is unknown (no connection, 5xx, the same key still at work or already used),
 * so the retry must carry the same Idempotency-Key and the server replays instead of charging twice. Mirrors
 * web/src/features/billing/attempt.tsx. */
export function keepsAttemptKey(error: unknown): boolean {
  if (error === null || error === undefined) return false;
  if (!(error instanceof ApiError)) return true;
  return error.status === 0 || error.status >= 500 || (error.status === 409 && (error.code === 'request-in-progress' || error.code === 'idempotency-key-reused'));
}

// shortcut: in memory only, so restarting the app frees the form; the server still refuses the key with other values.
const held = new Map<string, string>();

/** One Idempotency-Key per purchase attempt. After an unknown outcome the attempt is LOCKED: same key, and the
 * screen must keep the same offer and card, offering only "try again", until the server answers (a 2xx or a
 * decline frees it with a fresh key). `scope` keeps the lock across a remount. */
export function useAttemptKey(scope = 'buy') {
  const [key, setKey] = useState(() => held.get(scope) ?? Crypto.randomUUID());
  const [locked, setLocked] = useState(() => held.has(scope));
  const settle = useCallback(
    (error: unknown) => {
      if (keepsAttemptKey(error)) {
        held.set(scope, key);
        setLocked(true);
      } else if (error === null || error === undefined || !held.has(scope) || (error instanceof ApiError && error.status === 402)) {
        held.delete(scope);
        setLocked(false);
        setKey(Crypto.randomUUID());
      }
    },
    [scope, key],
  );
  return { key, locked, settle };
}

export function useCheckoutProvider() {
  const { tenant } = useApp();
  return useQuery({ queryKey: ['checkout-provider', tenant?.slug], queryFn: () => portal.checkoutProvider(), staleTime: Infinity, retry: false });
}

/** `value` is the chosen processor token ('' while none); `onChange` gets the next one. */
export function NewCard({ value, onChange }: { value: string; onChange: (token: string) => void }) {
  const provider = useCheckoutProvider();
  if (provider.isLoading) return <Loading />;
  if (provider.error) return <ErrorBox error={provider.error} />;
  if (provider.data !== 'fake') {
    return (
      <Surface>
        <Body>Card payment in the app is not available yet. Buy on the web portal, or at the front desk.</Body>
      </Surface>
    );
  }
  return (
    <Surface>
      <Small muted={false}>Test processor: development only. No real money moves and no card number is entered.</Small>
      {FAKE_CARDS.map((card) => (
        <Row key={card.token} title={card.label} subtitle={card.token === value ? 'Selected' : undefined} onPress={() => onChange(card.token)} />
      ))}
    </Surface>
  );
}
