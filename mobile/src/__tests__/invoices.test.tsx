import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';

import Invoices from '../app/invoices';

const mockListInvoices = jest.fn();
jest.mock('../adapters', () => ({
  portal: {
    isDemo: false,
    listInvoices: (id: string) => mockListInvoices(id),
    listPaymentMethods: async () => [{ id: 'pm1', kind: 'card', brand: 'visa', last4: '4242', is_autopay: false }],
  },
}));
jest.mock('../lib/app-state', () => ({
  useApp: () => ({ tenant: { slug: 'court' } }),
  useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled'),
}));
jest.mock('../lib/query', () => ({ useOnline: () => true }));
const self = { client: { id: 'c1', first_name: 'Pat', last_name: 'Lee', preferred_name: null, home_location_id: null }, basis: 'self' };
jest.mock('../lib/household', () => ({ useHousehold: () => ({ actingFor: self, members: [self] }), clientName: () => 'Pat Lee' }));
// The app config is off (demo mode, or the member app switched off): amounts must not depend on it.
jest.mock('../lib/hooks', () => ({ useAppConfig: () => ({ data: undefined }) }));
jest.mock('../ui/NewCard', () => ({ useCheckoutProvider: () => ({ data: 'fake' }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));

const invoice = (over: Record<string, unknown> = {}) => ({
  id: 'inv1', number: 1042, bill_to_client_id: 'c1', invoice_on: '2026-11-01', due_on: '2026-11-15', is_autopay: false,
  status: 'open', currency: 'EUR', total_minor: 4500, balance_minor: 4500, is_past_due: false, charges: [], ...over,
});

const renderInvoices = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Invoices />
    </QueryClientProvider>,
  );

it('shows amounts in the invoice currency and lets the member pay', async () => {
  mockListInvoices.mockResolvedValue([invoice()]);
  await renderInvoices();
  expect(await screen.findByText(/Total €45\.00 · €45\.00 due/)).toBeTruthy();
  expect(mockListInvoices).toHaveBeenCalledWith('c1');
  await screen.findByText(/Saved method: visa ending 4242/);
  expect(screen.getByLabelText('Pay now').props.accessibilityState.disabled).toBe(false);
});

it('keeps Pay disabled while no amount can be shown', async () => {
  // e.g. an invoice cached offline before the list carried its currency
  mockListInvoices.mockResolvedValue([invoice({ currency: undefined })]);
  await renderInvoices();
  expect(await screen.findByText(/Total … · … due/)).toBeTruthy();
  await screen.findByText(/Saved method: visa ending 4242/);
  expect(screen.getByLabelText('Pay now').props.accessibilityState.disabled).toBe(true);
});
