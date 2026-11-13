// APP-05 tile catalogue: one line per tile type. The server keeps the same list (TILE_TYPES in
// backend/app/modules/engagement/domain/app_config.py) and the staff editor its labels (TILE_LABELS in
// web/src/features/engagement/AppConfigPage.tsx). To add a type: one line in each of the three.
import type { Href } from 'expo-router';

import type { AppConfig, HomeScreen } from '../adapters/types';

type Feature = keyof AppConfig['features'];
export type TileType = { label: string; href: Href; feature?: Feature };

export const TILES: Record<string, TileType> = {
  book: { label: 'Book a class', href: '/schedule', feature: 'booking' },
  card: { label: 'My card', href: '/card', feature: 'membership_card' },
  memberships: { label: 'Memberships', href: '/memberships' },
  invoices: { label: 'Invoices', href: '/invoices' },
  notifications: { label: 'Notifications', href: '/inbox' },
  facility: { label: 'Facility info', href: '/facility' },
  // Phase 11 C2. shortcut: the server's TILE_TYPES and the staff editor's TILE_LABELS do not list these yet, so
  // a saved layout cannot include them; they show on the built-in home until both lists gain them.
  news: { label: 'News & info', href: '/news' },
  contacts: { label: 'Contacts', href: '/contacts' },
  favorites: { label: 'Favourites', href: '/favorites' },
  feedback: { label: 'Feedback', href: '/feedback' },
  try_us: { label: 'Try us', href: '/try-us' },
};

/** The built-in home, used until the facility saves a layout (or when the app config cannot be read). */
export const BUILT_IN: HomeScreen = {
  // "Try us" is for visitors (linked from sign-in); members see it only if the facility adds the tile.
  tiles: Object.keys(TILES)
    .filter((type) => type !== 'try_us')
    .map((type) => ({ type, caption: null, style: 'small' })),
  design: { columns: 2, corners: 'rounded' },
};

export type ResolvedTile = TileType & { key: string; caption: string; large: boolean };

/** The tiles to draw: the saved layout or the built-in one, skipping unknown types (an older app build) and
 * tiles whose feature the facility switched off. */
export function resolveTiles(config: Pick<AppConfig, 'home_screen' | 'features'> | null | undefined): { tiles: ResolvedTile[]; design: HomeScreen['design'] } {
  const layout = config?.home_screen ?? BUILT_IN;
  const tiles = layout.tiles.flatMap((tile, i): ResolvedTile[] => {
    const known = TILES[tile.type];
    if (!known || (known.feature && config?.features && !config.features[known.feature])) return [];
    return [{ ...known, key: `${tile.type}-${i}`, caption: tile.caption?.trim() || known.label, large: tile.style === 'large' }];
  });
  return { tiles, design: layout.design };
}
