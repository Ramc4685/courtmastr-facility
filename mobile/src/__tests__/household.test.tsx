import AsyncStorage from '@react-native-async-storage/async-storage';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';

import type { ActableClient } from '../adapters/types';
import { clientName, HouseholdProvider, useHousehold } from '../lib/household';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

const mockSignOut = jest.fn();
jest.mock('../lib/app-state', () => ({
  useApp: () => ({ tenant: { slug: 'club', name: 'Club', city: null }, status: 'signedIn', signOut: mockSignOut }),
  useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled'),
}));

const member = (id: string, basis: ActableClient['basis'], first: string): ActableClient => ({
  client: { id, first_name: first, last_name: 'Doe', preferred_name: null, member_number: null, status: 'active', home_location_id: 'l1', photo_url: null },
  basis,
  relationship_label: basis === 'self' ? null : 'Child',
});
let mockHousehold: ActableClient[] = [];
const mockListActableClients = jest.fn(async () => mockHousehold);
jest.mock('../adapters', () => ({ portal: { listActableClients: () => mockListActableClients() } }));

function Probe() {
  const { actingFor } = useHousehold();
  return <Text testID="acting">{actingFor ? clientName(actingFor) : 'none'}</Text>;
}

function renderHousehold() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={qc}>
      <HouseholdProvider>
        <ProfileSwitcher />
        <Probe />
      </HouseholdProvider>
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await AsyncStorage.clear();
  mockSignOut.mockClear();
  mockHousehold = [member('self', 'self', 'Morgan'), member('avery', 'relationship', 'Avery'), member('sam', 'managed_profile', 'Sam')];
});

it('defaults to the guardian and switches to a dependent instantly, without signing out', async () => {
  await renderHousehold();
  await waitFor(() => expect(screen.getByTestId('acting').props.children).toBe('Morgan Doe'));
  await fireEvent.press(screen.getByLabelText('Act for Avery Doe'));
  expect(screen.getByTestId('acting').props.children).toBe('Avery Doe');
  expect(screen.getByLabelText('Act for Avery Doe').props.accessibilityState.selected).toBe(true);
  expect(mockSignOut).not.toHaveBeenCalled();
  expect(mockListActableClients).toHaveBeenCalledTimes(1);
  await act(async () => {});
  expect(await AsyncStorage.getItem('fh.actingFor.club')).toBe('"avery"');
});

it('remembers the selection across launches', async () => {
  await AsyncStorage.setItem('fh.actingFor.club', '"sam"');
  await renderHousehold();
  await waitFor(() => expect(screen.getByTestId('acting').props.children).toBe('Sam Doe'));
});

it('falls back to the guardian when the selected dependent leaves the household', async () => {
  await AsyncStorage.setItem('fh.actingFor.club', '"avery"');
  mockHousehold = [member('self', 'self', 'Morgan')];
  await renderHousehold();
  await waitFor(() => expect(screen.getByTestId('acting').props.children).toBe('Morgan Doe'));
  // A one-person household shows no switcher at all.
  await act(async () => {});
  expect(screen.queryByLabelText(/Act for/)).toBeNull();
});
