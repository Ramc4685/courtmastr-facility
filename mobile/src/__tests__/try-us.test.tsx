import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import TryUs, { THANKS } from '../app/try-us';

const mockRequestTrial = jest.fn();
jest.mock('../adapters', () => ({ portal: { requestTrial: (r: unknown) => mockRequestTrial(r) } }));
jest.mock('../lib/app-state', () => ({ useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled') }));
jest.mock('../lib/query', () => ({ useOnline: () => true }));
const location = { id: 'l1', public_name: 'North', time_zone: 'America/Chicago' };
jest.mock('../lib/hooks', () => ({ useLocations: () => ({ data: [location] }), useHomeLocation: () => location }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));

async function submit() {
  await fireEvent.changeText(screen.getByLabelText('Name'), ' Pat ');
  await fireEvent.changeText(screen.getByLabelText('Email'), 'pat@example.com');
  await fireEvent.press(screen.getByRole('button', { name: 'Send request' }));
  await waitFor(() => expect(screen.getByText(THANKS)).toBeTruthy());
}

it.each([
  ['stored', () => Promise.resolve()],
  ['refused', () => Promise.reject(new Error('rate-limited'))],
])('shows the same thank-you message when the request is %s', async (_, outcome) => {
  mockRequestTrial.mockImplementation(outcome);
  await render(<TryUs />);
  await submit();
  expect(mockRequestTrial).toHaveBeenLastCalledWith({ name: 'Pat', email: 'pat@example.com', phone: null, interest: null, message: null, location_id: 'l1' });
});
