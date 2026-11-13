import { portal } from '../adapters';
import { ApiError, networkError, problemFrom } from '../api/errors';
import type { PublicLocation } from '../api/types';
import { config, tenantBase } from './config';
import { readJson, writeJson } from './storage';
import { BUNDLED_BRAND, DEMO_BRANDS, type TenantBrand, type Theme } from './theme';

export type Tenant = { slug: string; name: string; city: string | null };

const SLUG = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$/;

export function normaliseSlug(input: unknown): string | null {
  if (typeof input !== 'string') return null;
  const slug = input.trim().toLowerCase();
  return SLUG.test(slug) ? slug : null;
}

/** Confirm a tenant exists by reading its public locations (real endpoint, no sign-in needed). */
export async function lookupTenant(slug: string): Promise<{ tenant: Tenant; locations: PublicLocation[] }> {
  const { baseUrl, headers } = tenantBase(slug);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1/public/locations?limit=50`, { headers });
  } catch (cause) {
    throw networkError(cause);
  }
  if (!response.ok) throw await problemFrom(response);
  const { data } = (await response.json()) as { data: PublicLocation[] };
  const brand = DEMO_BRANDS[slug];
  const first = data[0];
  return {
    tenant: { slug, name: brand?.appName ?? first?.public_name ?? slug, city: first?.city ?? null },
    locations: data,
  };
}

const brandKey = (slug: string) => `fh.brand.${slug}`;

/** Instant brand for first paint: last-known-good from the API, else the bundled theme. Never waits. */
export async function cachedBrand(slug: string): Promise<{ brand: TenantBrand; source: Theme['brand']['source'] }> {
  const cached = await readJson<TenantBrand>(brandKey(slug));
  if (cached) return { brand: cached, source: 'cached' };
  const demo = DEMO_BRANDS[slug];
  return demo ? { brand: demo, source: 'demo' } : { brand: BUNDLED_BRAND, source: 'bundled' };
}

/** Fetch GET /public/app-config. In demo mode, or when it fails, keep what we have. */
export async function fetchBrand(slug: string): Promise<TenantBrand | null> {
  if (config.portalAdapter === 'demo') return null;
  try {
    const cfg = await portal.getAppConfig();
    // Colours are the tenant brand colours; null keeps the bundled ones (theme.ts checks contrast either way).
    const brand: TenantBrand = {
      primary: cfg.theme.primary ?? undefined,
      accent: cfg.theme.accent ?? undefined,
      appName: cfg.app_name,
      logoUrl: cfg.icon_url,
    };
    await writeJson(brandKey(slug), brand);
    return brand;
  } catch (error) {
    if (error instanceof ApiError || error instanceof Error) return null;
    throw error;
  }
}
