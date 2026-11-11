// Original design tokens. Tenants override only primary/accent/logo at runtime (ADR 0006 section 1); the
// on-colours are derived here so a tenant colour can never produce unreadable text (WCAG 2.1 AA, 4.5:1).

export type Palette = {
  background: string;
  surface: string;
  surfaceAlt: string;
  text: string;
  textMuted: string;
  border: string;
  primary: string;
  onPrimary: string;
  accent: string;
  danger: string;
  success: string;
  warning: string;
  warningSurface: string;
  demoSurface: string;
  onDemo: string;
};

export type Theme = {
  scheme: 'light' | 'dark';
  colors: Palette;
  space: (n: number) => number;
  radius: { sm: number; md: number; lg: number };
  font: { body: number; small: number; title: number; heading: number };
  brand: { appName: string; logoUrl: string | null; source: 'tenant' | 'cached' | 'bundled' | 'demo' };
};

export type TenantBrand = { primary?: string; accent?: string; appName?: string; logoUrl?: string | null };

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1]!, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function luminance(hex: string): number {
  const rgb = parseHex(hex);
  if (!rgb) return 0;
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The readable text colour on a background: white or near-black, whichever contrasts more. */
export function onColor(background: string): string {
  return contrast(background, '#FFFFFF') >= contrast(background, '#111827') ? '#FFFFFF' : '#111827';
}

/** Darken (light scheme) or lighten (dark scheme) a brand colour until text on the surface reads at 4.5:1. */
export function readableOn(color: string, surface: string): string {
  let rgb = parseHex(color);
  if (!rgb) return color;
  const toward = luminance(surface) > 0.5 ? 0 : 255;
  for (let i = 0; i < 20 && contrast(toHex(rgb), surface) < 4.5; i++) {
    rgb = rgb.map((c) => Math.round(c + (toward - c) * 0.12)) as [number, number, number];
  }
  return toHex(rgb);
}

const toHex = (rgb: [number, number, number]) => `#${rgb.map((c) => c.toString(16).padStart(2, '0')).join('')}`.toUpperCase();

const BASE = {
  light: {
    background: '#F6F7F9', surface: '#FFFFFF', surfaceAlt: '#EEF1F5', text: '#111827', textMuted: '#4B5563',
    border: '#D5DAE1', danger: '#B42318', success: '#067647', warning: '#93370D', warningSurface: '#FEF0C7',
    demoSurface: '#EDE9FE', onDemo: '#4C1D95',
  },
  dark: {
    background: '#0B0F17', surface: '#151B26', surfaceAlt: '#1E2633', text: '#F3F4F6', textMuted: '#AAB2BF',
    border: '#2E3847', danger: '#FDA29B', success: '#75E0A7', warning: '#FEC84B', warningSurface: '#3B2A0B',
    demoSurface: '#2E1F5E', onDemo: '#DDD6FE',
  },
};

export const BUNDLED_BRAND: Required<TenantBrand> = {
  primary: '#1F6FEB',
  accent: '#0E9384',
  appName: 'Courtmastr Facility',
  logoUrl: null,
};

export function buildTheme(scheme: 'light' | 'dark', brand: TenantBrand, source: Theme['brand']['source']): Theme {
  const base = BASE[scheme];
  const primaryRaw = parseHex(brand.primary ?? '') ? brand.primary! : BUNDLED_BRAND.primary;
  const accentRaw = parseHex(brand.accent ?? '') ? brand.accent! : BUNDLED_BRAND.accent;
  // Primary is used both as a fill (with onPrimary text) and as link text on the surface.
  const primary = readableOn(primaryRaw, base.surface);
  return {
    scheme,
    colors: { ...base, primary, onPrimary: onColor(primary), accent: readableOn(accentRaw, base.surface) },
    space: (n) => n * 4,
    radius: { sm: 6, md: 10, lg: 16 },
    font: { body: 16, small: 13, title: 22, heading: 18 },
    brand: { appName: brand.appName ?? BUNDLED_BRAND.appName, logoUrl: brand.logoUrl ?? null, source },
  };
}

/** Bundled per-tenant brands used by the demo adapter until GET /public/app-config exists. */
export const DEMO_BRANDS: Record<string, TenantBrand> = {
  'courtside-demo': { primary: '#C2410C', accent: '#0F766E', appName: 'Courtside Demo Club' },
  'riverside-athletic': { primary: '#1D4ED8', accent: '#7C3AED', appName: 'Riverside Athletic Center' },
};
