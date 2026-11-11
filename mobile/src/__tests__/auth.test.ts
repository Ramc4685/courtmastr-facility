import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import { api, resetClients, unwrap } from '../api/client';
import { ApiError } from '../api/errors';
import { consumeMagicLink, extractLinkToken, signInWithPassword, signOut } from '../lib/auth';
import { accessToken, activeSession, clearSession, loadSession } from '../lib/session';
import { grant, json, mockFetch } from '../test/helpers';

const store = (SecureStore as unknown as { __store: Map<string, string> }).__store;

beforeEach(async () => {
  store.clear();
  await AsyncStorage.clear();
  resetClients();
  await loadSession('courtside-demo');
});

describe('password sign-in', () => {
  it('signs in as a mobile client and keeps tokens only in the secure store', async () => {
    const calls = mockFetch([() => json(grant())]);
    await signInWithPassword('courtside-demo', ' member@example.com ', 'pw');

    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/auth/sign-in');
    expect(calls[0]!.headers['x-tenant-slug']).toBe('courtside-demo');
    expect(calls[0]!.body).toEqual({ email: 'member@example.com', password: 'pw', audience: 'client', client_kind: 'mobile' });
    expect(JSON.parse(store.get('fh.session.courtside-demo')!).refresh).toBe('fhr_refresh_1');
    const asyncKeys = await AsyncStorage.getAllKeys();
    for (const k of asyncKeys) expect(await AsyncStorage.getItem(k)).not.toContain('fhr_');
  });

  it('surfaces the problem+json detail on bad credentials', async () => {
    mockFetch([() => json({ status: 401, code: 'invalid-credentials', title: 'Invalid credentials', detail: 'Email or password is incorrect.' }, 401)]);
    await expect(signInWithPassword('courtside-demo', 'a@b.co', 'nope')).rejects.toMatchObject({ code: 'invalid-credentials', status: 401 });
    expect(activeSession()).toBeNull();
  });
});

describe('session refresh', () => {
  it('refreshes ahead of expiry and rotates the stored refresh token', async () => {
    mockFetch([() => json(grant({ access_expires_at: new Date(Date.now() + 10_000).toISOString() }))]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    const calls = mockFetch([() => json(grant({ access_token: 'fhs_access_2', refresh_token: 'fhr_refresh_2' }))]);

    expect(await accessToken()).toBe('fhs_access_2');
    expect(calls[0]!.url).toMatch(/\/auth\/refresh$/);
    expect(calls[0]!.body).toEqual({ refresh_token: 'fhr_refresh_1' });
    expect(JSON.parse(store.get('fh.session.courtside-demo')!).refresh).toBe('fhr_refresh_2');
  });

  it('retries a request once after a 401 with a refreshed token', async () => {
    mockFetch([() => json(grant())]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    const calls = mockFetch([
      () => json({ status: 401, code: 'unauthenticated' }, 401),
      () => json(grant({ access_token: 'fhs_access_2', refresh_token: 'fhr_refresh_2' })),
      () => json({ principal: {}, tenant: { name: 'Courtside' } }),
    ]);
    const me = await unwrap(api().GET('/api/v1/me'));
    expect((me as { tenant: { name: string } }).tenant.name).toBe('Courtside');
    expect(calls[0]!.headers.authorization).toBe('Bearer fhs_access_1');
    expect(calls[2]!.headers.authorization).toBe('Bearer fhs_access_2');
  });

  it('ends the session when the refresh token is rejected', async () => {
    mockFetch([() => json(grant({ access_expires_at: new Date(Date.now() - 1000).toISOString() }))]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    mockFetch([() => json({ status: 401, code: 'refresh-reused' }, 401)]);
    expect(await accessToken()).toBeNull();
    expect(store.has('fh.session.courtside-demo')).toBe(false);
  });

  it('keeps the session when offline instead of signing the member out', async () => {
    mockFetch([() => json(grant({ access_expires_at: new Date(Date.now() - 1000).toISOString() }))]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    mockFetch([() => Promise.reject(new TypeError('Network request failed'))]);
    expect(await accessToken()).toBe('fhs_access_1');
    expect(activeSession()).not.toBeNull();
  });
});

describe('magic link', () => {
  it('reads the token only from the fragment or as a bare token', () => {
    expect(extractLinkToken('https://courtside-demo.example.com/auth/magic-link#token=abcDEF123456789xyz')).toBe('abcDEF123456789xyz');
    expect(extractLinkToken('facilityhub://auth/magic-link#token=abcDEF123456789xyz&next=/')).toBe('abcDEF123456789xyz');
    expect(extractLinkToken('abcDEF123456789xyz')).toBe('abcDEF123456789xyz');
    expect(extractLinkToken('https://x.example.com/auth/magic-link?token=abcDEF123456789xyz')).toBeNull();
    expect(extractLinkToken('short')).toBeNull();
    expect(extractLinkToken('')).toBeNull();
  });

  it('consumes the token in a POST body, never in the URL', async () => {
    const calls = mockFetch([() => json(grant())]);
    await consumeMagicLink('courtside-demo', 'abcDEF123456789xyz');
    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/auth/magic-links/consume');
    expect(calls[0]!.url).not.toContain('abcDEF');
    expect(calls[0]!.body).toEqual({ token: 'abcDEF123456789xyz', client_kind: 'mobile' });
    expect(activeSession()?.access).toBe('fhs_access_1');
  });
});

describe('sign-out', () => {
  it('revokes on the server and removes the local session', async () => {
    mockFetch([() => json(grant())]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    const calls = mockFetch([() => new Response(null, { status: 204 })]);
    await signOut('courtside-demo');
    expect(calls[0]!.url).toMatch(/\/auth\/sign-out$/);
    expect(store.has('fh.session.courtside-demo')).toBe(false);
  });

  it('still signs out locally when offline', async () => {
    mockFetch([() => json(grant())]);
    await signInWithPassword('courtside-demo', 'a@b.co', 'pw');
    mockFetch([() => Promise.reject(new TypeError('offline'))]);
    await signOut('courtside-demo');
    expect(activeSession()).toBeNull();
  });
});

it('maps network failures to ApiError(network)', async () => {
  mockFetch([() => Promise.reject(new TypeError('offline'))]);
  await clearSession('courtside-demo');
  await expect(unwrap(api().GET('/api/v1/public/locations'))).rejects.toBeInstanceOf(ApiError);
});
