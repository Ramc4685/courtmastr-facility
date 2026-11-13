import { Pressable, ScrollView, Text } from 'react-native';

import type { PublicLocation } from '../api/types';
import { useTheme } from '../lib/app-state';

/** Pick one of the facility's locations; hidden when there is only one. */
export function LocationPicker({ locations, value, onChange }: { locations: PublicLocation[]; value: string | undefined; onChange(id: string): void }) {
  const t = useTheme();
  if (locations.length < 2) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: t.space(2) }} accessibilityRole="tablist" accessibilityLabel="Location">
      {locations.map((l) => {
        const selected = l.id === value;
        return (
          <Pressable
            key={l.id}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            onPress={() => onChange(l.id)}
            style={{
              minHeight: 44,
              justifyContent: 'center',
              paddingHorizontal: t.space(4),
              borderRadius: 999,
              backgroundColor: selected ? t.colors.primary : t.colors.surface,
              borderWidth: 1,
              borderColor: selected ? t.colors.primary : t.colors.border,
            }}
          >
            <Text style={{ color: selected ? t.colors.onPrimary : t.colors.text, fontWeight: '600' }}>{l.public_name}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
