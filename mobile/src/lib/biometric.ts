import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';

const KEY = 'fh.biometric';

export async function biometricAvailable(): Promise<boolean> {
  return (await LocalAuthentication.hasHardwareAsync()) && (await LocalAuthentication.isEnrolledAsync());
}

export const biometricEnabled = async () => (await SecureStore.getItemAsync(KEY)) === '1';

export async function setBiometricEnabled(enabled: boolean) {
  if (enabled) await SecureStore.setItemAsync(KEY, '1');
  else await SecureStore.deleteItemAsync(KEY);
}

export async function unlockWithBiometrics(): Promise<boolean> {
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Unlock your account',
    fallbackLabel: 'Use passcode',
  });
  return result.success;
}
