// APP-17 anonymous screen counts: counted in memory, sent in batches of at most 50 names (the server's limit)
// by the root layout every 60 s and when the app goes to the background, only while signed in.
import type { UsageItem } from '../adapters/types';

export const BATCH = 50;
const NAME = /^[a-z0-9_.-]{1,60}$/;
// Refuse anything that looks like an id (long digit or hex runs) even if it fits the server's pattern.
const ID_LIKE = /[0-9a-f]{8,}|\d{4,}/;

let pending = new Map<string, number>();

/** Count one view of a screen. Names come from route names, never from params; bad names are dropped. */
export function track(name: string) {
  if (!NAME.test(name) || ID_LIKE.test(name)) return;
  pending.set(name, (pending.get(name) ?? 0) + 1);
}

/** Forget unsent counts (sign-out: nothing is sent while signed out). */
export function clearUsage() {
  pending = new Map();
}

/** Send everything counted so far, 50 names per request. A failed batch is dropped, not retried: these are
 * best-effort counts and must never pile up or block the app. */
export async function flushUsage(send: (items: UsageItem[]) => Promise<void>) {
  const items = [...pending].map(([name, count]): UsageItem => ({ kind: 'screen', name, count: Math.min(count, 100) }));
  pending = new Map();
  for (let i = 0; i < items.length; i += BATCH) {
    try {
      await send(items.slice(i, i + BATCH));
    } catch {
      // best effort
    }
  }
}

/** `screen.<route>` from Expo Router segments: groups dropped, `[param]` kept as its name, never its value. */
export function screenName(segments: string[]): string {
  const parts = segments.filter((s) => !s.startsWith('(')).map((s) => s.replace(/[^a-z0-9_-]/g, ''));
  return `screen.${parts.join('.') || 'index'}`.slice(0, 60);
}
