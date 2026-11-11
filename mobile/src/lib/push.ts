// Push plumbing (ADR 0006 section 6). The OS prompt comes after a soft prompt at a relevant moment (first
// booking or the profile toggle), never at first launch. Registration goes through the portal adapter.
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { portal } from '../adapters';
import { config } from './config';

export type PushResult = { status: 'registered'; deviceId: string | undefined } | { status: 'denied' | 'unsupported'; reason: string };

export function installNotificationHandlers(onOpen: (data: Record<string, unknown>) => void): () => void {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: true,
    }),
  });
  const sub = Notifications.addNotificationResponseReceivedListener((response) =>
    onOpen((response.notification.request.content.data ?? {}) as Record<string, unknown>),
  );
  return () => sub.remove();
}

export async function registerForPush(locationId: string | null = null): Promise<PushResult> {
  if (!Device.isDevice) return { status: 'unsupported', reason: 'Push needs a physical device; simulators cannot receive it.' };
  const existing = await Notifications.getPermissionsAsync();
  const granted = existing.granted || (await Notifications.requestPermissionsAsync()).granted;
  if (!granted) return { status: 'denied', reason: 'Notifications are turned off in Settings.' };
  const projectId = (Constants.expoConfig?.extra?.eas as { projectId?: string } | undefined)?.projectId;
  if (!projectId) return { status: 'unsupported', reason: 'No EAS project id configured for push in this build.' };
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
  const saved = await portal.registerDevice({
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    push_token: token,
    location_id: locationId,
    app_version: config.appVersion,
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
    is_push_enabled: true,
  });
  return { status: 'registered', deviceId: saved.id };
}
