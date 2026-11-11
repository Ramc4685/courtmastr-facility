import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, render, waitFor } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';

import { resetClients } from '../api/client';
import { AppStateProvider, useApp, type AppState } from '../lib/app-state';
import { saveGrant } from '../lib/session';
import { grant, json, mockFetch } from '../test/helpers';

const store = (SecureStore as unknown as { __store: Map<string, string> }).__store;
const club = { slug: 'courtside-demo', name: 'Courtside', city: null };

let app: AppState;
const capture = (state: AppState) => (app = state);
function Probe() {
  capture(useApp());
  return null;
}

beforeEach(async () => {
  store.clear();
  await AsyncStorage.clear();
  resetClients();
  mockFetch(Array.from({ length: 10 }, () => () => json({ status: 404, code: 'not-found' }, 404)));
});

it('re-applies the biometric lock when a deep link selects a tenant that has a stored session', async () => {
  await saveGrant('courtside-demo', grant() as never);
  await SecureStore.setItemAsync('fh.biometric', '1');
  await render(<AppStateProvider><Probe /></AppStateProvider>);
  await waitFor(() => expect(app.status).toBe('noTenant'));
  await act(() => app.selectTenant(club));
  expect(app.status).toBe('locked');
});

it('only expects a magic link this device requested', async () => {
  await AsyncStorage.setItem('fh.tenant', JSON.stringify(club));
  await render(<AppStateProvider><Probe /></AppStateProvider>);
  await waitFor(() => expect(app.status).toBe('signedOut'));
  expect(await app.magicLinkExpected()).toBe(false);
  mockFetch([() => new Response(null, { status: 204 })]);
  await act(() => app.requestMagicLink('member@example.com'));
  expect(await app.magicLinkExpected()).toBe(true);
});
