import { Tabs } from 'expo-router/js-tabs';
import { Text, type ColorValue } from 'react-native';

import { useTheme } from '../../lib/app-state';

const glyph = (char: string) =>
  function TabIcon({ color }: { color: ColorValue }) {
    return <Text style={{ color, fontSize: 18 }} accessibilityElementsHidden importantForAccessibility="no">{char}</Text>;
  };

export default function TabsLayout() {
  const t = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: t.colors.surface },
        headerTitleStyle: { color: t.colors.text },
        tabBarStyle: { backgroundColor: t.colors.surface, borderTopColor: t.colors.border },
        tabBarActiveTintColor: t.colors.primary,
        tabBarInactiveTintColor: t.colors.textMuted,
        sceneStyle: { backgroundColor: t.colors.background },
      }}
    >
      <Tabs.Screen name="home" options={{ title: 'Home', tabBarIcon: glyph('⌂') }} />
      <Tabs.Screen name="schedule" options={{ title: 'Schedule', tabBarIcon: glyph('▦') }} />
      <Tabs.Screen name="card" options={{ title: 'Card', tabBarIcon: glyph('▣') }} />
      <Tabs.Screen name="bookings" options={{ title: 'My bookings', tabBarIcon: glyph('✓') }} />
      <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: glyph('≡') }} />
    </Tabs>
  );
}
