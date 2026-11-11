// Offline-aware data layer: queries are persisted to AsyncStorage so a screen that loaded once renders
// from cache with no network (ADR 0006 section 4, v1 offline scope is read-only).
import NetInfo from '@react-native-community/netinfo';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { focusManager, onlineManager, QueryClient } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';
import { AppState } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError } from '../api/errors';

const WEEK = 7 * 24 * 3_600_000;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: WEEK,
      networkMode: 'offlineFirst',
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
    mutations: { networkMode: 'online' },
  },
});

export const persister = createAsyncStoragePersister({ storage: AsyncStorage, key: 'fh.query-cache' });
export const persistOptions = { persister, maxAge: WEEK, buster: '1' };

onlineManager.setEventListener((setOnline) =>
  NetInfo.addEventListener((state) => setOnline(state.isConnected !== false)),
);
focusManager.setEventListener((setFocused) => {
  const sub = AppState.addEventListener('change', (s) => setFocused(s === 'active'));
  return () => sub.remove();
});

export function useOnline(): boolean {
  return useSyncExternalStore(
    (cb) => onlineManager.subscribe(cb),
    () => onlineManager.isOnline(),
  );
}

/** Drop every cached screen (sign-out, tenant switch). */
export async function clearQueryCache() {
  queryClient.clear();
  await persister.removeClient();
}
