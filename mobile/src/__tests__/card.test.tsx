import AsyncStorage from '@react-native-async-storage/async-storage';
import { render, screen } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';

import type { ActableClient, AppCard } from '../adapters/types';
import { cardCode, cardStatus, decodeCardToken, loadCards, syncCards } from '../lib/card';
import { buildTheme } from '../lib/theme';
import { code128Bits } from '../ui/Barcode';
import { MemberCard } from '../ui/MemberCard';

jest.mock('../lib/app-state', () => ({ useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled') }));
jest.mock('react-native-qrcode-svg', () => {
  const { Text } = require('react-native');
  return ({ value }: { value: string }) => <Text testID="qr">{value}</Text>;
});

const store = (SecureStore as unknown as { __store: Map<string, string> }).__store;
const HOUR = 3_600_000;
const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');

function card(clientId: string, iatMs: number, ttlHours = 72): AppCard {
  const iat = Math.floor(iatMs / 1000);
  const exp = iat + ttlHours * 3600;
  return {
    credential_id: `cred-${clientId}`,
    client_id: clientId,
    device_label: 'inst-1',
    card_payload: `FH1.${b64({ kid: 'k1', cred: `cred-${clientId}`, inst: 'inst-1', iat, exp })}.sig`,
    issued_at: new Date(iat * 1000).toISOString(),
    expires_at: new Date(exp * 1000).toISOString(),
  };
}

const client = (id: string, basis: ActableClient['basis'], first: string, member: string | null): ActableClient => ({
  client: { id, first_name: first, last_name: 'Doe', preferred_name: null, member_number: member, status: 'active', home_location_id: 'l1', photo_url: null },
  basis,
  relationship_label: basis === 'self' ? null : 'Child',
});

beforeEach(async () => {
  store.clear();
  await AsyncStorage.clear();
});

describe('card token', () => {
  it('decodes FH1 tokens and rejects anything else', async () => {
    const t = card('c1', Date.now());
    expect(decodeCardToken(t.card_payload)).toMatchObject({ cred: 'cred-c1', inst: 'inst-1' });
    expect(decodeCardToken('FH2.abc.def')).toBeNull();
    expect(decodeCardToken('FH1.not-json.sig')).toBeNull();
    expect(decodeCardToken('garbage')).toBeNull();
  });

  it('is valid, then due for refresh at half-life, then expired', async () => {
    const now = Date.now();
    const t = card('c1', now);
    expect(cardStatus(t, now + HOUR)).toBe('valid');
    expect(cardStatus(t, now + 40 * HOUR)).toBe('expiring');
    expect(cardStatus(t, now + 73 * HOUR)).toBe('expired');
    expect(cardStatus(undefined, now)).toBe('missing');
  });

  // Vector from backend access/domain/cards.py: seed(UUID, bytes(range(32))) and qr_text at 1794000000.
  const SEED = '01a1cb37-0c92-77d0-b7c5-fbed2ada71bd.AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8';

  it('derives the same rotating QR as the server from a real card seed, which never expires on the phone', async () => {
    expect(await cardCode(SEED, 1_794_000_000_000)).toBe('fhq.01a1cb37-0c92-77d0-b7c5-fbed2ada71bd.59800000.ujn9qdv11ZSDMxdEnH0WUA');
    expect(await cardCode(SEED, 1_794_000_030_000)).toMatch(/^fhq\.01a1cb37-[^.]+\.59800001\./);
    const real = { credential_id: 'k', client_id: 'c1', device_label: null, card_payload: SEED, issued_at: '', expires_at: null };
    expect(cardStatus(real, Date.now() + 1000 * HOUR)).toBe('valid');
    expect(await cardCode('FH1.demo.DEMO', 0)).toBe('FH1.demo.DEMO');
  });
});

describe('syncCards', () => {
  const self = client('self', 'self', 'Morgan', 'M-1');
  const kid = client('kid', 'relationship', 'Avery', 'M-2');

  it('issues a card for every client the identity can act for and keeps tokens in the secure store', async () => {
    const issue = jest.fn(async (id: string) => card(id, Date.now()));
    const out = await syncCards('club', [self, kid], issue);
    expect(issue.mock.calls.map((c) => c[0])).toEqual(['self', 'kid']);
    expect(out.display.map((d) => d.label)).toEqual(['You', 'Child']);
    expect(Object.keys(JSON.parse(store.get('fh.cards.club')!))).toEqual(['self', 'kid']);
    expect(await AsyncStorage.getItem('fh.carddisplay.club')).not.toContain('FH1.');
  });

  it('reuses valid tokens and re-issues expiring ones', async () => {
    const now = Date.now();
    await syncCards('club', [self, kid], async (id) => card(id, id === 'kid' ? now - 50 * HOUR : now));
    const issue = jest.fn(async (id: string) => card(id, now));
    await syncCards('club', [self, kid], issue, now);
    expect(issue.mock.calls.map((c) => c[0])).toEqual(['kid']);
  });

  it('drops the card of a dependent who is no longer in the household, so it cannot reappear', async () => {
    await syncCards('club', [self, kid], async (id) => card(id, Date.now()));
    await syncCards('club', [self], async (id) => card(id, Date.now()));
    const stored = await loadCards('club');
    expect(stored.display.map((d) => d.clientId)).toEqual(['self']);
    expect(Object.keys(stored.tokens)).toEqual(['self']);
  });

  it('loads cards from local storage alone (offline, no session)', async () => {
    await syncCards('club', [self, kid], async (id) => card(id, Date.now()));
    globalThis.fetch = jest.fn(() => Promise.reject(new Error('offline'))) as unknown as typeof fetch;
    const stored = await loadCards('club');
    expect(stored.display).toHaveLength(2);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

describe('MemberCard', () => {
  const display = { clientId: 'kid', name: 'Avery Doe', memberNumber: 'M-2', label: 'Child' };

  it('shows the signed QR when the token is valid', async () => {
    const now = Date.now();
    await render(<MemberCard display={display} token={card('kid', now)} tenantName="Club" now={now} online demo={false} width={360} />);
    expect(screen.getByText('Ready to scan')).toBeTruthy();
    expect(screen.getByTestId('qr').props.children).toMatch(/^FH1\./);
  });

  it('still renders when expired and offline: refresh needed, member number and static barcode', async () => {
    const now = Date.now();
    await render(<MemberCard display={display} token={card('kid', now - 80 * HOUR)} tenantName="Club" now={now} online={false} demo={false} width={360} />);
    expect(screen.getByText('Refresh needed')).toBeTruthy();
    expect(screen.getByText('Offline')).toBeTruthy();
    expect(screen.getByText('M-2')).toBeTruthy();
    expect(screen.queryByTestId('qr')).toBeNull();
    expect(screen.getByLabelText('Barcode for M-2')).toBeTruthy();
  });

  it('labels demo credentials so they are never mistaken for real ones', async () => {
    const now = Date.now();
    await render(<MemberCard display={display} token={card('kid', now)} tenantName="Club" now={now} online demo width={360} />);
    expect(screen.getByText('Demo credential')).toBeTruthy();
    expect(screen.getByText(/will not check you in/)).toBeTruthy();
  });
});

it('encodes Code 128 bars for the static fallback', async () => {
  const bits = code128Bits('M-2');
  expect(bits).toMatch(/^[01]+$/);
  expect(bits.startsWith('11010')).toBe(true); // start code
  expect(buildTheme('dark', {}, 'bundled').scheme).toBe('dark');
});
