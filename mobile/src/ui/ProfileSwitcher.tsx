import { Pressable, ScrollView, Text } from 'react-native';

import { useTheme } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';

/** Persistent "acting for" switcher. Instant and local; no sign-out (beats the reference app, APP-01). */
export function ProfileSwitcher() {
  const t = useTheme();
  const { members, actingFor, switchTo } = useHousehold();
  if (members.length < 2) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: t.space(2) }} accessibilityRole="tablist" accessibilityLabel="Acting for">
      {members.map((m) => {
        const selected = m.client.id === actingFor?.client.id;
        const name = clientName(m);
        return (
          <Pressable
            key={m.client.id}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={`Act for ${name}${m.basis === 'self' ? ' (you)' : ''}`}
            onPress={() => switchTo(m.client.id)}
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
            <Text style={{ color: selected ? t.colors.onPrimary : t.colors.text, fontWeight: '600', fontSize: t.font.body }}>
              {m.basis === 'self' ? `${name} (you)` : name}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
