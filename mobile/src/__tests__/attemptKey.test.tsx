import { act, renderHook } from '@testing-library/react-native';

import { ApiError } from '../api/errors';
import { keepsAttemptKey, useAttemptKey } from '../ui/NewCard';

jest.mock('../adapters', () => ({ portal: {} }));
jest.mock('../lib/app-state', () => ({ useApp: () => ({}) }));

const err = (status: number, code = `http-${status}`) => new ApiError({ status, code });

describe('useAttemptKey (S1)', () => {
  it('keeps the key on a lost answer and frees it only on an answer', () => {
    expect(keepsAttemptKey(err(0, 'network'))).toBe(true);
    expect(keepsAttemptKey(err(503))).toBe(true);
    expect(keepsAttemptKey(err(409, 'idempotency-key-reused'))).toBe(true);
    expect(keepsAttemptKey(err(402))).toBe(false);
    expect(keepsAttemptKey(err(422))).toBe(false);
  });

  it('locks after an unknown outcome, stays locked through a refusal, frees on a decline, and survives a remount', async () => {
    const first = await renderHook(() => useAttemptKey('t1'));
    const key = first.result.current.key;
    await act(async () => first.result.current.settle(err(0, 'network')));
    expect(first.result.current).toMatchObject({ key, locked: true });
    await act(async () => first.result.current.settle(err(422)));
    expect(first.result.current).toMatchObject({ key, locked: true });
    await first.unmount();
    const again = await renderHook(() => useAttemptKey('t1'));
    expect(again.result.current).toMatchObject({ key, locked: true });
    await act(async () => again.result.current.settle(err(402)));
    expect(again.result.current.locked).toBe(false);
    expect(again.result.current.key).not.toBe(key);
  });
});
