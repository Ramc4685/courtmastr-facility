import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import { useRef } from 'react';
import { Alert } from 'react-native';

import { portal } from '../adapters';
import { registerForPush } from './push';
import { readJson, writeJson } from './storage';

/** First booking is the moment for the soft push prompt (ADR 0006 section 6), asked once per install. */
async function maybeAskForPush() {
  if (await readJson<boolean>('fh.pushAsked')) return;
  await writeJson('fh.pushAsked', true);
  Alert.alert('Get booking reminders?', 'We can notify you about reminders, waitlist spots and facility news.', [
    { text: 'Not now', style: 'cancel' },
    { text: 'Turn on', onPress: () => void registerForPush() },
  ]);
}

/** Book and cancel for a client. One Idempotency-Key per intent, reused if the user retries a failed tap. */
export function useBookingActions(clientId: string | undefined) {
  const qc = useQueryClient();
  const keys = useRef(new Map<string, string>());
  const invalidate = () => qc.invalidateQueries({ predicate: (q) => ['sessions', 'bookings'].includes(String(q.queryKey[0])) });

  const book = useMutation({
    mutationFn: (sessionId: string) => {
      const intent = `${clientId}:${sessionId}`;
      const idempotencyKey = keys.current.get(intent) ?? Crypto.randomUUID();
      keys.current.set(intent, idempotencyKey);
      return portal.createEnrollment({ clientId: clientId!, sessionId, idempotencyKey });
    },
    onSuccess: (_e, sessionId) => {
      keys.current.delete(`${clientId}:${sessionId}`);
      void invalidate();
      void maybeAskForPush();
    },
  });

  const cancel = useMutation({
    mutationFn: (enrollmentId: string) => portal.cancelEnrollment(enrollmentId),
    onSuccess: () => void invalidate(),
  });

  return { book, cancel };
}
