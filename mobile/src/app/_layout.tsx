import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { router, Stack, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { portal } from '../adapters';
import { AppStateProvider, useApp } from '../lib/app-state';
import { HouseholdProvider } from '../lib/household';
import { installNotificationHandlers } from '../lib/push';
import { persistOptions, queryClient } from '../lib/query';
import { clearUsage, flushUsage, screenName, track } from '../lib/usage';

function Navigator() {
  const { status, theme } = useApp();
  const c = theme.colors;

  useEffect(
    () =>
      installNotificationHandlers(() => {
        // Payloads carry ids only (ADR 0006 s6); detail is fetched after open. The inbox is the landing place.
        void queryClient.invalidateQueries({ queryKey: ['inbox'] });
        router.push('/inbox');
      }),
    [],
  );

  // APP-17: count screen views while signed in; send every 60 s and on background; nothing while signed out.
  const segments: string[] = useSegments();
  const route = screenName(segments);
  const signedIn = status === 'signedIn';
  useEffect(() => {
    if (signedIn) track(route);
  }, [route, signedIn]);
  useEffect(() => {
    if (!signedIn) return clearUsage();
    const send = () => void flushUsage((items) => portal.recordUsage(items));
    const timer = setInterval(send, 60_000);
    const sub = AppState.addEventListener('change', (next) => next === 'background' && send());
    return () => {
      clearInterval(timer);
      sub.remove();
    };
  }, [signedIn]);

  return (
    <>
      <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: c.surface },
          headerTintColor: c.primary,
          headerTitleStyle: { color: c.text },
          contentStyle: { backgroundColor: c.background },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="t/[slug]" options={{ title: 'Opening facility' }} />
        <Stack.Protected guard={status === 'noTenant' || status === 'signedOut' || status === 'signedIn'}>
          <Stack.Screen name="facilities" options={{ title: 'Find your facility' }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'signedOut' || status === 'signedIn'}>
          <Stack.Screen name="contacts" options={{ title: 'Contacts' }} />
          <Stack.Screen name="try-us" options={{ title: 'Try us' }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'signedOut'}>
          <Stack.Screen name="sign-in" options={{ title: 'Sign in' }} />
          <Stack.Screen name="auth/magic-link" options={{ title: 'Signing in' }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'locked'}>
          <Stack.Screen name="unlock" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'signedIn'}>
          <Stack.Screen name="(tabs)" options={{ headerShown: false, title: 'Back' }} />
          <Stack.Screen name="memberships" options={{ title: 'Memberships & packages' }} />
          <Stack.Screen name="buy" options={{ title: 'Buy' }} />
          <Stack.Screen name="wallet" options={{ title: 'Wallet pass' }} />
          <Stack.Screen name="invoices" options={{ title: 'Invoices' }} />
          <Stack.Screen name="progress" options={{ title: 'Progress' }} />
          <Stack.Screen name="inbox" options={{ title: 'Notifications' }} />
          <Stack.Screen name="facility" options={{ title: 'Facility info' }} />
          <Stack.Screen name="profile" options={{ title: 'Profile' }} />
          <Stack.Screen name="news" options={{ title: 'News & info' }} />
          <Stack.Screen name="feedback" options={{ title: 'Feedback' }} />
          <Stack.Screen name="favorites" options={{ title: 'Favourites' }} />
        </Stack.Protected>
      </Stack>
    </>
  );
}

export default function RootLayout() {
  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
      <AppStateProvider>
        <HouseholdProvider>
          <Navigator />
        </HouseholdProvider>
      </AppStateProvider>
    </PersistQueryClientProvider>
  );
}
