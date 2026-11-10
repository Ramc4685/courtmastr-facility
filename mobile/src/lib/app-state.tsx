import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

import { resetClients } from '../api/client';
import type { Principal } from '../api/types';
import * as auth from './auth';
import { biometricEnabled } from './biometric';
import { clearCards } from './card';
import { config } from './config';
import { clearQueryCache } from './query';
import { activeSession, loadSession, subscribeSession } from './session';
import { readJson, removeKey, writeJson } from './storage';
import { cachedBrand, fetchBrand, normaliseSlug, type Tenant } from './tenant';
import { buildTheme, type TenantBrand, type Theme } from './theme';

export type AuthStatus = 'loading' | 'noTenant' | 'signedOut' | 'locked' | 'signedIn';

export type AppState = {
  status: AuthStatus;
  tenant: Tenant | null;
  principal: Principal | null;
  theme: Theme;
  selectTenant(tenant: Tenant): Promise<void>;
  leaveTenant(): Promise<void>;
  signIn(email: string, password: string): Promise<void>;
  requestMagicLink(email: string): Promise<void>;
  consumeMagicLink(token: string): Promise<void>;
  /** True when this device asked for a sign-in link recently; other links need explicit confirmation (login CSRF). */
  magicLinkExpected(): Promise<boolean>;
  signOut(): Promise<void>;
  unlocked(): void;
};

const Ctx = createContext<AppState | null>(null);
const MAGIC_LINK_WINDOW_MS = 20 * 60_000;
const TENANT_KEY = 'fh.tenant';

export function AppStateProvider({ children }: { children: ReactNode }) {
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [brand, setBrand] = useState<{ brand: TenantBrand; source: Theme['brand']['source'] }>({ brand: {}, source: 'bundled' });
  const [ready, setReady] = useState(false);
  const [locked, setLocked] = useState(false);
  const [principal, setPrincipal] = useState<Principal | null>(null);

  useEffect(() => subscribeSession(() => setPrincipal(activeSession()?.principal ?? null)), []);

  // Any activation with a stored session re-applies the biometric lock, so a deep link (t/<slug>) can never
  // skip unlock. Only unlocked() clears it, after a successful LocalAuthentication check.
  const activate = useCallback(async (next: Tenant) => {
    resetClients();
    setTenant(next);
    setBrand(await cachedBrand(next.slug));
    const session = await loadSession(next.slug);
    setLocked(!!session && (await biometricEnabled()));
    void fetchBrand(next.slug).then((fresh) => fresh && setBrand({ brand: fresh, source: 'tenant' }));
  }, []);

  useEffect(() => {
    (async () => {
      const pinned = config.pinnedTenant ? { slug: config.pinnedTenant, name: config.pinnedTenant, city: null } : null;
      const saved = pinned ?? (await readJson<Tenant>(TENANT_KEY));
      if (saved && normaliseSlug(saved.slug)) await activate(saved);
      else if (saved) {
        console.warn('Ignoring a saved facility with an invalid code');
        await removeKey(TENANT_KEY);
      }
      setReady(true);
    })();
  }, [activate]);

  const value = useMemo<AppState>(() => {
    const status: AuthStatus = !ready ? 'loading' : !tenant ? 'noTenant' : !principal ? 'signedOut' : locked ? 'locked' : 'signedIn';
    return {
      status,
      tenant,
      principal,
      theme: buildTheme(scheme, brand.brand, brand.source),
      selectTenant: async (next) => {
        await writeJson(TENANT_KEY, next);
        await clearQueryCache();
        await activate(next);
      },
      leaveTenant: async () => {
        await removeKey(TENANT_KEY);
        await clearQueryCache();
        setTenant(null);
        setBrand({ brand: {}, source: 'bundled' });
      },
      signIn: async (email, password) => {
        await auth.signInWithPassword(tenant!.slug, email, password);
      },
      requestMagicLink: async (email) => {
        await auth.requestMagicLink(email);
        await writeJson(`fh.magicRequested.${tenant!.slug}`, Date.now());
      },
      magicLinkExpected: async () => {
        const at = await readJson<number>(`fh.magicRequested.${tenant!.slug}`);
        return typeof at === 'number' && Date.now() - at < MAGIC_LINK_WINDOW_MS;
      },
      consumeMagicLink: async (token) => {
        await auth.consumeMagicLink(tenant!.slug, token);
        await removeKey(`fh.magicRequested.${tenant!.slug}`);
      },
      signOut: async () => {
        const slug = tenant!.slug;
        await auth.signOut(slug);
        await clearCards(slug);
        await removeKey(`fh.actingFor.${slug}`);
        await clearQueryCache();
        setLocked(false);
      },
      unlocked: () => setLocked(false),
    };
  }, [ready, tenant, principal, locked, scheme, brand, activate]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error('useApp outside AppStateProvider');
  return value;
}

export const useTheme = () => useApp().theme;
