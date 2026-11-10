// Tokens live only in the platform secure store (Keychain / Keystore), one entry per tenant, because a
// person who belongs to two facilities holds two sessions (ADR 0006 section 5). Never AsyncStorage.
import * as SecureStore from 'expo-secure-store';

import { ApiError, networkError, problemFrom } from '../api/errors';
import type { AuthSessionOut, Principal } from '../api/types';
import { tenantBase } from './config';

export type StoredSession = {
  access: string;
  refresh: string;
  accessExpiresAt: string;
  principal: Principal;
};

const key = (slug: string) => `fh.session.${slug}`;
const REFRESH_MARGIN_MS = 60_000;

let active: { slug: string; session: StoredSession | null } | null = null;
let inflight: Promise<StoredSession | null> | null = null;
const listeners = new Set<() => void>();

const notify = () => listeners.forEach((fn) => fn());
export function subscribeSession(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const activeSlug = () => active?.slug ?? null;
export const activeSession = () => active?.session ?? null;

export async function loadSession(slug: string): Promise<StoredSession | null> {
  const raw = await SecureStore.getItemAsync(key(slug));
  active = { slug, session: raw ? (JSON.parse(raw) as StoredSession) : null };
  notify();
  return active.session;
}

/** Store a grant from sign-in, magic link or refresh. Mobile grants carry both tokens in the body. */
export async function saveGrant(slug: string, grant: AuthSessionOut): Promise<StoredSession> {
  if (!grant.access_token || !grant.refresh_token) {
    throw new ApiError({ status: 500, code: 'missing-tokens', detail: 'The server did not return mobile tokens.' });
  }
  const session: StoredSession = {
    access: grant.access_token,
    refresh: grant.refresh_token,
    accessExpiresAt: grant.access_expires_at,
    principal: grant.principal,
  };
  await SecureStore.setItemAsync(key(slug), JSON.stringify(session));
  active = { slug, session };
  notify();
  return session;
}

export async function clearSession(slug: string): Promise<void> {
  await SecureStore.deleteItemAsync(key(slug));
  if (active?.slug === slug) active = { slug, session: null };
  notify();
}

/** Rotate the refresh token. Single-flight: concurrent callers share one request (the server accepts a
 * just-rotated token for 20 seconds, but one call is cleaner). A rejected refresh ends the session. */
export function refreshSession(): Promise<StoredSession | null> {
  if (inflight) return inflight;
  const current = active;
  if (!current?.session) return Promise.resolve(null);
  const { baseUrl, headers } = tenantBase(current.slug);
  inflight = (async () => {
    let response: Response;
    try {
      response = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: current.session!.refresh }),
      });
    } catch (cause) {
      throw networkError(cause);
    }
    if (response.status === 401) {
      await clearSession(current.slug);
      return null;
    }
    if (!response.ok) throw await problemFrom(response);
    return saveGrant(current.slug, (await response.json()) as AuthSessionOut);
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** A usable access token, refreshing first when it expires within a minute. Null when signed out.
 * Offline with an expired token: returns the stale token and lets the request fail as a network error. */
export async function accessToken(now = Date.now()): Promise<string | null> {
  const session = active?.session;
  if (!session) return null;
  if (Date.parse(session.accessExpiresAt) - now > REFRESH_MARGIN_MS) return session.access;
  try {
    return (await refreshSession())?.access ?? null;
  } catch (error) {
    if (error instanceof ApiError && error.isNetwork) return session.access;
    throw error;
  }
}
