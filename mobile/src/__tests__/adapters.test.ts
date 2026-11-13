import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

import { portal } from '../adapters';
import { apiAdapter } from '../adapters/api';
import { demoAdapter, resetDemo } from '../adapters/demo';
import { resetClients } from '../api/client';
import { signInWithPassword } from '../lib/auth';
import { loadSession } from '../lib/session';
import { buildTheme, contrast } from '../lib/theme';
import { grant, json, mockFetch, type Call } from '../test/helpers';

const store = (SecureStore as unknown as { __store: Map<string, string> }).__store;
const page = (data: unknown[], next: string | null = null) => ({ data, page: { has_more: next !== null, next_cursor: next } });

describe('adapter switch', () => {
  it('defaults to the real API; the demo adapter labels itself as demo', () => {
    expect(portal).toBe(apiAdapter);
    expect(apiAdapter.isDemo).toBe(false);
    expect(demoAdapter.isDemo).toBe(true);
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

  it('books with the caller-supplied Idempotency-Key and the chosen package', async () => {
    const calls = mockFetch([() => json({ id: 'e1', client_id: 'c1', session_id: 's1', status: 'enrolled', target_kind: 'session' }, 201)]);
    const out = await apiAdapter.createEnrollment({ clientId: 'c1', sessionId: 's1', clientPackageId: 'p1', idempotencyKey: 'intent-1' });
    expect(out).toEqual({ id: 'e1', client_id: 'c1', session_id: 's1', status: 'enrolled' });
    expect(calls[0]).toMatchObject({ method: 'POST', body: { client_id: 'c1', session_id: 's1', client_package_id: 'p1' } });
    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/portal/enrollments');
    expect(calls[0]!.headers['idempotency-key']).toBe('intent-1');
  });

  it('pays invoices with a saved method id only, never card data', async () => {
    const payment = { id: 'p1', receipt_number: 7, amount_minor: 500, currency: 'USD', status: 'processing' };
    const calls = mockFetch([() => json({ payment, client_secret: 'cs_1', credit_applied_minor: 0 }, 201)]);
    const out = await apiAdapter.payInvoices({ invoiceIds: ['i1'], paymentMethodId: 'pm1', idempotencyKey: 'pay-1' });
    expect(calls[0]!.body).toEqual({ invoice_ids: ['i1'], payment_method_id: 'pm1' });
    expect(calls[0]!.headers['idempotency-key']).toBe('pay-1');
    expect(out).toMatchObject({ id: 'p1', status: 'processing', invoice_ids: ['i1'], next_action: { kind: 'confirm' } });
  });

  it('treats a payment fully covered by account credit as succeeded', async () => {
    mockFetch([() => json({ payment: null, client_secret: null, credit_applied_minor: 500 }, 201)]);
    const out = await apiAdapter.payInvoices({ invoiceIds: ['i1'], paymentMethodId: 'pm1', idempotencyKey: 'pay-2' });
    expect(out).toMatchObject({ status: 'succeeded', next_action: null });
  });

  it('maps merged portal clients and invoices to the app shapes', async () => {
    const person = { id: 'c1', first_name: 'Ann', last_name: 'Lee', preferred_name: null, member_number: 'M1', can_edit: true };
    mockFetch([() => json({ data: [{ ...person, authority: 'self' }, { ...person, id: 'c2', authority: 'guardian' }] })]);
    const [self, dep] = await apiAdapter.listActableClients();
    expect(self).toMatchObject({ basis: 'self', relationship_label: null, client: { id: 'c1', home_location_id: null } });
    expect(dep).toMatchObject({ basis: 'relationship', relationship_label: 'Guardian' });

    mockFetch([() => json(page([{ id: 'i1', status: 'open', past_due_since_on: '2026-11-01' }, { id: 'i2', status: 'open', past_due_since_on: null }]))]);
    const [late, current] = await apiAdapter.listInvoices('c1');
    expect(late).toMatchObject({ is_past_due: true, charges: [] });
    expect(current!.is_past_due).toBe(false);
  });

  describe('schedule', () => {
    const listing = (id: string, over: Record<string, unknown> = {}) => ({
      session_id: id, location_id: 'l1', title: `Class ${id}`, starts_at: '2026-11-12T15:00:00Z', ends_at: '2026-11-12T16:00:00Z',
      spots_left: 3, is_bookable: true, can_join_waitlist: false, reason: null, ...over,
    });
    const pkg = (id: string, over: Record<string, unknown> = {}) => ({
      id, status: 'active', is_unlimited: false, sessions_available_count: 2, reservation_type_id: `rt-${id}`, location_id: 'l1', ...over,
    });
    // Routes by URL: the adapter fires its reads concurrently, so arrival order is not fixed.
    function serve() {
      const route = (call: Call) => {
        const url = new URL(call.url);
        if (url.pathname.endsWith('/portal/enrollments'))
          return json(page([{ id: 'e2', client_id: 'dep 1', session_id: 's2', status: 'enrolled', target_kind: 'session' }]));
        if (url.pathname.endsWith('/portal/client-packages')) return json(page([pkg('p1'), pkg('p0', { sessions_available_count: 0 })]));
        if (url.searchParams.get('reservation_type_id') === 'rt-p1') return json([listing('s1')]);
        return json([
          listing('s1'),
          listing('s2'),
          listing('s3', { is_bookable: false, can_join_waitlist: true, reason: 'full', spots_left: 0 }),
          listing('s4', { is_bookable: false, reason: 'members-only' }),
          listing('s5', { is_bookable: false, reason: 'cutoff-passed', title: null }),
        ]);
      };
      return mockFetch(Array.from({ length: 4 }, () => route));
    }

    it('scopes every read to the acting-for client and joins bookings and packages', async () => {
      const calls = serve();
      const rows = await apiAdapter.listSessionListings({ clientId: 'dep 1', from: '2026-11-10T00:00:00Z', to: '2026-11-11T00:00:00Z' });
      const urls = calls.map((c) => new URL(c.url));
      expect(urls.every((u) => u.searchParams.get('client_id') === 'dep 1')).toBe(true);
      const base = urls.find((u) => u.pathname.endsWith('/session-listings') && !u.searchParams.has('reservation_type_id'))!;
      expect(base.searchParams.get('starts_at[gte]')).toBe('2026-11-10T00:00:00Z');
      const enrollments = urls.find((u) => u.pathname.endsWith('/portal/enrollments'))!;
      expect([enrollments.searchParams.get('status'), enrollments.searchParams.get('target_kind')]).toEqual(['enrolled', 'session']);
      // Only the package with sessions left is asked about; the exhausted one is skipped.
      expect(urls.filter((u) => u.searchParams.has('reservation_type_id')).map((u) => u.searchParams.get('location_id'))).toEqual(['l1']);
      expect(rows.map((r) => [r.session_id, r.eligibility, r.my_enrollment_id, r.eligible_client_package_ids])).toEqual([
        ['s1', 'bookable', null, ['p1']],
        ['s2', 'already_booked', 'e2', []],
        ['s3', 'full_waitlist', null, []],
        ['s4', 'needs_purchase', null, []],
        ['s5', 'closed', null, []],
      ]);
      expect(rows[4]!.name).toBe('Session');
    });

    it('lists my bookings from the same joined window', async () => {
      serve();
      const bookings = await apiAdapter.listBookings('dep 1');
      expect(bookings).toHaveLength(1);
      expect(bookings[0]).toMatchObject({ enrollment: { id: 'e2', client_id: 'dep 1', status: 'enrolled' }, session: { session_id: 's2', name: 'Class s2' } });
    });
  });

  it('maps cards, devices, payment methods and progress from the real shapes', async () => {
    let calls = mockFetch([() => json({ credential_id: 'k1', client_id: 'c1', device_label: 'inst', card_payload: 'seed', issued_at: 'x' }, 201)]);
    expect(await apiAdapter.issueAppCard('c1', 'inst')).toMatchObject({ card_payload: 'seed', expires_at: null });
    expect(calls[0]!.body).toEqual({ client_id: 'c1', device_label: 'inst' });

    mockFetch([() => json({ id: 'd1', platform: 'ios', is_push_enabled: true, last_active_at: null }, 201)]);
    expect(await apiAdapter.registerDevice({ platform: 'ios', push_token: 'tok' })).toMatchObject({ id: 'd1', push_token: 'tok' });

    const method = { id: 'pm1', kind: 'card', brand: 'visa', last4: '4242', is_autopay: true, client_id: 'c1', created_at: 'x' };
    mockFetch([() => json([{ ...method, status: 'active' }, { ...method, id: 'pm2', status: 'removed' }])]);
    expect(await apiAdapter.listPaymentMethods()).toEqual([{ id: 'pm1', kind: 'card', brand: 'visa', last4: '4242', is_autopay: true }]);

    calls = mockFetch([() => json([{ assessment_field_id: 'f1', field_name: 'Weight', latest_value: '81.5' }])]);
    expect(await apiAdapter.listProgress('c1')).toMatchObject([{ field_name: 'Weight' }]);
    expect(calls[0]!.url).toBe('http://localhost:8150/api/v1/portal/assessment-bests?client_id=c1');
  });

  it('searches the shared directory anonymously and reads the public app config', async () => {
    let calls = mockFetch([]);
    expect(await apiAdapter.searchDirectory('c')).toEqual([]); // under two letters the server is not asked
    expect(calls).toHaveLength(0);
    calls = mockFetch([() => json({ data: [{ tenant_id: 't1', slug: 'court', name: 'Court Club', host: 'court.example' }] })]);
    expect(await apiAdapter.searchDirectory(' court ')).toEqual([
      { tenant_id: 't1', slug: 'court', name: 'Court Club', host: 'court.example', city: null, icon_url: null },
    ]);
    expect(calls[0]!.url).toContain('/api/v1/public/app-directory?q=court&limit=20');
    expect(calls[0]!.headers.authorization).toBeUndefined();
    calls = mockFetch([() => json({ tenant_id: 't1', app_name: 'Court', theme: {}, features: {}, schedule: {}, portal: {} })]);
    expect(await apiAdapter.getAppConfig()).toMatchObject({ app_name: 'Court', icon_url: null, home_screen: null });
    expect(calls[0]!.url).toContain('/api/v1/public/app-config');
  });

  it('surfaces problem+json from a missing endpoint as an ApiError', async () => {
    mockFetch([() => json({ status: 404, code: 'not-found', title: 'Not found' }, 404)]);
    await expect(apiAdapter.listInbox()).rejects.toMatchObject({ status: 404, code: 'not-found' });
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
