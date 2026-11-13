import { api, unwrap } from '../api/client';
import { ApiError } from '../api/errors';
import { clearSession, saveGrant } from './session';

type Grant = Parameters<typeof saveGrant>[1];

/** A sign-in may answer with an MFA challenge (Phase 8). The app has no MFA screen yet, so it says so. */
function grantOrRefuse(result: Grant | { mfa_token: string }): Grant {
  if ('mfa_token' in result) {
    throw new ApiError({ status: 403, code: 'mfa-required', detail: 'This account uses two-step sign-in. Sign in on the web portal for now.' });
  }
  return result;
}

export async function signInWithPassword(slug: string, email: string, password: string) {
  const grant = await unwrap(
    api().POST('/api/v1/auth/sign-in', {
      body: { email: email.trim(), password, audience: 'client', client_kind: 'mobile' },
    }),
  );
  return saveGrant(slug, grantOrRefuse(grant));
}

/** Always resolves the same way whether or not the email exists (no account enumeration server-side). */
export async function requestMagicLink(email: string) {
  await unwrap(api().POST('/api/v1/auth/magic-links', { body: { email: email.trim(), audience: 'client' } }));
}

/**
 * The emailed link carries its token in the URL fragment (security-baseline 17.2), e.g.
 * `https://<tenant>/auth/magic-link#token=...` or the app scheme equivalent. Accepts the whole link or the
 * bare token. A token in a query string is refused: that link would already have been logged somewhere.
 */
export function extractLinkToken(input: string): string | null {
  const text = input.trim();
  if (!text) return null;
  const hash = text.indexOf('#');
  if (hash >= 0) {
    const params = new URLSearchParams(text.slice(hash + 1));
    return params.get('token');
  }
  if (/[?&]token=/.test(text)) return null;
  return /^[A-Za-z0-9_\-.~]{16,200}$/.test(text) ? text : null;
}

export async function consumeMagicLink(slug: string, token: string) {
  const grant = await unwrap(api().POST('/api/v1/auth/magic-links/consume', { body: { token, client_kind: 'mobile' } }));
  return saveGrant(slug, grantOrRefuse(grant));
}

/** Revoke server-side when reachable; the local session is removed either way. */
export async function signOut(slug: string) {
  try {
    await unwrap(api().POST('/api/v1/auth/sign-out'));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  } finally {
    await clearSession(slug);
  }
}
