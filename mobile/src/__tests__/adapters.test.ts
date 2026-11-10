import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import { portal } from '../adapters';
import { apiAdapter } from '../adapters/api';
import { demoAdapter, resetDemo } from '../adapters/demo';
import { resetClients } from '../api/client';
import { signInWithPassword } from '../lib/auth';
import { loadSession } from '../lib/session';
import { buildTheme, contrast } from '../lib/theme';
import { grant, json, mockFetch } from '../test/helpers';

const store = (SecureStore as unknown as { __store: Map<string, string> }).__store;
const page = (data: unknown[], next: string | null = null) => ({ data, page: { has_more: next !== null, next_cursor: next } });

describe('adapter switch', () => {
  it('defaults to the demo adapter, which labels itself as demo', () => {
    expect(portal).toBe(demoAdapter);
    expect(portal.isDemo).toBe(true);
    expect(apiAdapter.isDemo).toBe(false);
  });
});

describe('demo adapter', () => {
  beforeEach(() => resetDemo());

  it('books once per intent, replays idempotently and cancels', async () => {
    const [session] = await demoAdapter.listSessionListings({ clientId: 'demo-client-self', from: new Date().toISOString(), to: new Date(Date.now() + 7 * 86_400_000).toISOString() });
    const args = { clientId: 'demo-client-self', sessionId: session!.session_id, idempotencyKey: 'k1' };
    const first = await demoAdapter.createEnrollment(args);
    expect((await demoAdapter.createEnrollment(args)).id).toBe(first.id);
    expect((await demoAdapter.cancelEnrollment(first.id)).status).toBe('cancelled');
  });

  it('keeps inbox read state and returns the stored read time on replay', async () => {
    const [item] = await demoAdapter.listInbox();
    const read = await demoAdapter.markInboxRead(item!.id);
    expect(read.read_at).not.toBeNull();
    expect((await demoAdapter.markInboxRead(item!.id)).read_at).toBe(read.read_at);
    expect((await demoAdapter.listInbox()).find((i) => i.id === item!.id)!.read_at).toBe(read.read_at);
  });

  it('issues demo card tokens that a scanner can tell are not real', async () => {
    const card = await demoAdapter.issueAppCard('demo-client-self', 'inst-1');
    expect(card.card_payload).toMatch(/^FH1\.[A-Za-z0-9_-]+\.DEMO$/);
  });
});

describe('api adapter', () => {
  beforeEach(async () => {
    store.clear();
    await AsyncStorage.clear();
    resetClients();
    await loadSession('courtside-demo');
    mockFetch([() => json(grant())]);
    await signInWithPassword('courtside-demo', 'member@example.com', 'pw');
  });

  it('follows keyset pages and sends the tenant and bearer headers', async () => {
    const calls = mockFetch([() => json(page([{ id: 'a' }], 'c2')), () => json(page([{ id: 'b' }]))]);
    expect(await apiAdapter.listInbox()).toEqual([{ id: 'a' }, { id: 'b' }]);
    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/portal/inbox?limit=200');
    expect(calls[1]!.url).toContain('cursor=c2');
    expect(calls[0]!.headers['x-tenant-slug']).toBe('courtside-demo');
    expect(calls[0]!.headers.authorization).toBe('Bearer fhs_access_1');
  });

  it('books with the caller-supplied Idempotency-Key and the planned body', async () => {
    const calls = mockFetch([() => json({ id: 'e1' }, 201)]);
    await apiAdapter.createEnrollment({ clientId: 'c1', sessionId: 's1', idempotencyKey: 'intent-1' });
    expect(calls[0]).toMatchObject({ method: 'POST', body: { client_id: 'c1', session_id: 's1' } });
    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/portal/enrollments');
    expect(calls[0]!.headers['idempotency-key']).toBe('intent-1');
  });

  it('pays invoices with a saved method id only, never card data', async () => {
    const calls = mockFetch([() => json({ id: 'p1', status: 'succeeded' }, 201)]);
    await apiAdapter.payInvoices({ invoiceIds: ['i1'], paymentMethodId: 'pm1', idempotencyKey: 'pay-1' });
    expect(calls[0]!.body).toEqual({ invoice_ids: ['i1'], payment_method_id: 'pm1' });
    expect(calls[0]!.headers['idempotency-key']).toBe('pay-1');
  });

  it('scopes session listings to the acting-for client', async () => {
    const calls = mockFetch([() => json(page([]))]);
    await apiAdapter.listSessionListings({ clientId: 'dep 1', from: '2026-11-10T00:00:00Z', to: '2026-11-11T00:00:00Z' });
    const url = new URL(calls[0]!.url);
    expect(url.pathname).toBe('/api/v1/portal/session-listings');
    expect(url.searchParams.get('acting_for')).toBe('dep 1');
    expect(url.searchParams.get('starts_at[gte]')).toBe('2026-11-10T00:00:00Z');
  });

  it('surfaces problem+json from a missing endpoint as an ApiError', async () => {
    mockFetch([() => json({ status: 404, code: 'not-found', title: 'Not found' }, 404)]);
    await expect(apiAdapter.listMemberships('c1')).rejects.toMatchObject({ status: 404, code: 'not-found' });
  });
});

describe('tenant theme', () => {
  it('keeps text on any brand colour at WCAG AA contrast', () => {
    for (const primary of ['#FFFF00', '#1F6FEB', '#C2410C', '#000000', '#7C3AED']) {
      for (const scheme of ['light', 'dark'] as const) {
        const t = buildTheme(scheme, { primary }, 'tenant');
        expect(contrast(t.colors.onPrimary, t.colors.primary)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
