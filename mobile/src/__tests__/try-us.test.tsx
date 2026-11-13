import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiError, networkError } from '../api/errors';
import TryUs, { NOT_SENT, THANKS } from '../app/try-us';

const mockRequestTrial = jest.fn();
jest.mock('../adapters', () => ({ portal: { requestTrial: (r: unknown) => mockRequestTrial(r) } }));
jest.mock('../lib/app-state', () => ({ useTheme: () => require('../lib/theme').buildTheme('light', {}, 'bundled') }));
jest.mock('../lib/query', () => ({ useOnline: () => true }));
const location = { id: 'l1', public_name: 'North', time_zone: 'America/Chicago' };
jest.mock('../lib/hooks', () => ({ useLocations: () => ({ data: [location] }), useHomeLocation: () => location }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));

const problem = (status: number, code: string) => new ApiError({ status, code });

async function submit() {
  await fireEvent.changeText(screen.getByLabelText('Name'), ' Pat ');
  await fireEvent.changeText(screen.getByLabelText('Email'), 'pat@example.com');
  await fireEvent.press(screen.getByRole('button', { name: 'Send request' }));
}

// Anti-enumeration: every answer the server gives looks the same to the visitor.
it.each([
  ['stored', () => Promise.resolve()],
  ['refused', () => Promise.reject(problem(422, 'validation-failed'))],
  ['rate limited', () => Promise.reject(problem(429, 'rate-limited'))],
])('shows the same thank-you message when the request is %s', async (_, outcome) => {
  mockRequestTrial.mockImplementation(outcome);
  await render(<TryUs />);
  await submit();
  await waitFor(() => expect(screen.getByText(THANKS)).toBeTruthy());
  expect(mockRequestTrial).toHaveBeenLastCalledWith({ name: 'Pat', email: 'pat@example.com', phone: null, interest: null, message: null, location_id: 'l1' });
});

// Nothing reached the server (offline) or it failed (5xx): say so and keep what was typed.
it.each([
  ['offline', () => Promise.reject(networkError(new TypeError('Network request failed')))],
  ['a server error', () => Promise.reject(problem(503, 'http-503'))],
])('says the request was not sent when %s', async (_, outcome) => {
  mockRequestTrial.mockImplementation(outcome);
  await render(<TryUs />);
  await submit();
  await waitFor(() => expect(screen.getByText(NOT_SENT)).toBeTruthy());
  expect(screen.queryByText(THANKS)).toBeNull();
  expect(screen.getByLabelText('Email').props.value).toBe('pat@example.com');
});
