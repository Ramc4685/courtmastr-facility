// Household switching (ADR 0006 section 5, ADR 0009 can_act_for): one sign-in, a local "acting for" choice,
// and every portal request names the client explicitly. No server-side "current profile", no re-login.
import { useQuery } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { portal, type ActableClient } from '../adapters';
import { useApp } from './app-state';
import { readJson, writeJson } from './storage';

type Household = {
  members: ActableClient[];
  actingFor: ActableClient | null;
  switchTo(clientId: string): void;
  isLoading: boolean;
};

const Ctx = createContext<Household | null>(null);

export function HouseholdProvider({ children }: { children: ReactNode }) {
  const { tenant, status } = useApp();
  const slug = tenant?.slug ?? '';
  // Kept per club, so another club's choice never carries over.
  const [selected, setSelected] = useState<{ slug: string; id: string | null }>({ slug: '', id: null });
  const selectedId = selected.slug === slug ? selected.id : null;
  const members = useQuery({
    queryKey: ['actable-clients', slug],
    queryFn: () => portal.listActableClients(),
    enabled: status === 'signedIn',
  });

  useEffect(() => {
    if (!slug) return;
    let current = true;
    // The stored choice only fills an empty selection: a switch made while it loads wins.
    void readJson<string>(`fh.actingFor.${slug}`).then((stored) => {
      if (current) setSelected((prev) => (prev.slug === slug && prev.id ? prev : { slug, id: stored }));
    });
    return () => {
      current = false;
    };
  }, [slug]);

  const value = useMemo<Household>(() => {
    const list = members.data ?? [];
    // A selection that is no longer in the list (relationship ended) falls back to the identity's own client.
    const actingFor = list.find((m) => m.client.id === selectedId) ?? list.find((m) => m.basis === 'self') ?? list[0] ?? null;
    return {
      members: list,
      actingFor,
      isLoading: members.isLoading,
      switchTo: (clientId) => {
        setSelected({ slug, id: clientId });
        void writeJson(`fh.actingFor.${slug}`, clientId);
      },
    };
  }, [members.data, members.isLoading, selectedId, slug]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useHousehold(): Household {
  const value = useContext(Ctx);
  if (!value) throw new Error('useHousehold outside HouseholdProvider');
  return value;
}

export const clientName = (m: ActableClient) =>
  [m.client.preferred_name ?? m.client.first_name, m.client.last_name].filter(Boolean).join(' ');
