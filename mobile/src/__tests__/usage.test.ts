import type { UsageItem } from '../adapters/types';
import { BATCH, clearUsage, flushUsage, screenName, track } from '../lib/usage';

beforeEach(() => clearUsage());

it('names screens from route segments, never from param values', () => {
  expect(screenName(['(tabs)', 'home'])).toBe('screen.home');
  expect(screenName(['t', '[slug]'])).toBe('screen.t.slug');
  expect(screenName(['try-us'])).toBe('screen.try-us');
  expect(screenName([])).toBe('screen.index');
});

it('sends at most 50 names per batch and sums repeats', async () => {
  for (let i = 0; i < 60; i++) track(`screen.s${String.fromCharCode(97 + (i % 26))}${String.fromCharCode(97 + Math.floor(i / 26))}`);
  track('screen.saa');
  const batches: UsageItem[][] = [];
  await flushUsage(async (items) => void batches.push(items));
  expect(batches.map((b) => b.length)).toEqual([BATCH, 10]);
  expect(batches[0]![0]).toEqual({ kind: 'screen', name: 'screen.saa', count: 2 });
  // Flushed counts are gone; an empty flush sends nothing.
  await flushUsage(async (items) => void batches.push(items));
  expect(batches).toHaveLength(2);
});

it('drops names that carry personal data or ids', async () => {
  ['screen.pat@example.com', 'screen.Profile', 'screen.0192f6a8c3d1', 'screen.member.12345', 'x'.repeat(61)].forEach(track);
  track('screen.news');
  const sent: UsageItem[] = [];
  await flushUsage(async (items) => void sent.push(...items));
  expect(sent).toEqual([{ kind: 'screen', name: 'screen.news', count: 1 }]);
});

it('forgets unsent counts on sign-out and survives a failed send', async () => {
  track('screen.news');
  clearUsage();
  const send = jest.fn(async () => {
    throw new Error('offline');
  });
  await flushUsage(send);
  expect(send).not.toHaveBeenCalled();
  track('screen.news');
  await expect(flushUsage(send)).resolves.toBeUndefined();
});
