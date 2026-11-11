import AsyncStorage from '@react-native-async-storage/async-storage';

/** Non-secret local state only (selected tenant, theme cache, card display data). Tokens use SecureStore. */
export async function readJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export const writeJson = (key: string, value: unknown) => AsyncStorage.setItem(key, JSON.stringify(value));
export const removeKey = (key: string) => AsyncStorage.removeItem(key);
