import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';

import Buy from '../app/buy';

const mockListOffers = jest.fn();
jest.mock('../adapters', () => ({ portal: { isDemo: false, listOffers: (id: string) => mockListOffers(id) } }));
jest.mock('../lib/app-state', () => ({
  useApp: () => ({ tenant: { slug: 'court' } }),
  useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled'),
}));
jest.mock('../lib/query', () => ({ useOnline: () => true }));
const self = { client: { id: 'c1', first_name: 'Pat', last_name: 'Lee', preferred_name: null, home_location_id: null }, basis: 'self' };
jest.mock('../lib/household', () => ({ useHousehold: () => ({ actingFor: self, members: [self] }), clientName: () => 'Pat Lee' }));
jest.mock('../lib/hooks', () => ({
  useLocations: () => ({ data: [{ id: 'l1' }] }),
  useAppConfig: () => ({ data: { currency: 'EUR' } }),
}));
jest.mock('../ui/NewCard', () => ({ NewCard: () => null, useAttemptKey: () => ({ key: 'k', locked: false, settle: () => undefined }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));

const renderBuy = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Buy />
    </QueryClientProvider>,
  );

it('lists the acting client offers in the facility currency, or the offer own currency when it has one', async () => {
  mockListOffers.mockResolvedValue([
    { kind: 'membership', id: 'm1', name: 'Monthly', price_minor: 8900, currency: null, detail: null },
    { kind: 'package', id: 'p1', name: 'Ten visits', price_minor: 12000, currency: 'GBP', detail: null },
  ]);
  await renderBuy();
  expect(await screen.findByText(/Membership · €89\.00/)).toBeTruthy();
  expect(screen.getByText(/Package · £120\.00/)).toBeTruthy();
  expect(mockListOffers).toHaveBeenCalledWith('c1');
});
