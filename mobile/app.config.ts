// One JS bundle, N native shells (ADR 0006 section 1). APP_VARIANT picks the shell's static identity;
// everything a tenant can change after install is runtime config loaded from the API.
import type { ExpoConfig } from 'expo/config';
import runtime from './runtime-version.json';

type Variant = {
  slug: string;
  name: string;
  scheme: string;
  iosBundleIdentifier: string;
  androidPackage: string;
  pinnedTenant: string | null;
};

const variantSlug = process.env.APP_VARIANT ?? 'shared';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const variant: Variant = require(`./variants/${variantSlug}.json`);

const config: ExpoConfig = {
  name: variant.name,
  slug: 'courtmastr-facility',
  version: '0.1.0',
  orientation: 'portrait',
  scheme: variant.scheme,
  icon: './assets/icon.png',
  userInterfaceStyle: 'automatic',
  runtimeVersion: runtime.runtimeVersion,
  updates: { fallbackToCacheTimeout: 0 },
  ios: {
    supportsTablet: true,
    bundleIdentifier: variant.iosBundleIdentifier,
    infoPlist: {
      FHVariant: variant.slug,
      FHTenantSlug: variant.pinnedTenant ?? '',
      NSFaceIDUsageDescription: 'Unlock your saved sign-in with Face ID.',
    },
  },
  android: {
    package: variant.androidPackage,
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    ['expo-local-authentication', { faceIDPermission: 'Unlock your saved sign-in with Face ID.' }],
    'expo-notifications',
    ['expo-splash-screen', { image: './assets/splash-icon.png', backgroundColor: '#0F172A', imageWidth: 160 }],
  ],
  experiments: { typedRoutes: false },
  extra: { variant: variant.slug, pinnedTenant: variant.pinnedTenant },
};

export default config;
