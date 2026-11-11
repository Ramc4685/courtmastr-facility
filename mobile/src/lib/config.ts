import Constants from 'expo-constants';

const pinned: unknown = Constants.expoConfig?.extra?.pinnedTenant;

export const config = {
  apiOrigin: process.env.EXPO_PUBLIC_API_ORIGIN ?? 'http://localhost:8150',
  platformDomain: process.env.EXPO_PUBLIC_PLATFORM_DOMAIN || null,
  // The real portal API by default; `demo` runs the app on in-app data with no backend (see src/adapters).
  portalAdapter: (process.env.EXPO_PUBLIC_PORTAL_ADAPTER === 'demo' ? 'demo' : 'api') as 'api' | 'demo',
  // shortcut: read from the JS config, which an OTA update could overwrite (ADR 0006 section 1 wants the
  // native Info.plist value); upgrade to a native-constants read before publishing a second branded shell.
  // Expo Go serialises a null extra as {}, so accept a non-empty string only.
  pinnedTenant: typeof pinned === 'string' && pinned ? pinned : null,
  appVersion: Constants.expoConfig?.version ?? '0.0.0',
};

/**
 * Base URL for a tenant: per-tenant host in production, one origin plus X-Tenant-Slug in development. The API
 * resolves the tenant from Host and falls back to the header (public routes) or the token (signed-in routes),
 * so http://localhost:<port> reaches courtside-demo without *.localhost DNS, which iOS does not resolve.
 */
export function tenantBase(slug: string): { baseUrl: string; headers: Record<string, string> } {
  if (config.platformDomain) return { baseUrl: `https://${slug}.${config.platformDomain}`, headers: {} };
  return { baseUrl: config.apiOrigin, headers: { 'X-Tenant-Slug': slug } };
}
