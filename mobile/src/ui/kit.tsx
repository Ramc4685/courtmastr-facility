// A small original component set. Colours come only from the theme tokens; every touch target is at least
// 44pt; text scales with the OS font size; interactive elements carry roles and labels.
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { messageFor } from '../api/errors';
import { useTheme } from '../lib/app-state';
import { useOnline } from '../lib/query';

export function Screen({
  children,
  onRefresh,
  refreshing = false,
  scroll = true,
}: {
  children: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  scroll?: boolean;
}) {
  const t = useTheme();
  const online = useOnline();
  const body = (
    <View style={{ padding: t.space(4), gap: t.space(3) }}>
      {!online && <OfflineBanner />}
      {children}
    </View>
  );
  return (
    <SafeAreaView edges={['left', 'right']} style={{ flex: 1, backgroundColor: t.colors.background }}>
      {scroll ? (
        <ScrollView
          contentInsetAdjustmentBehavior="automatic"
          refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}
        >
          {body}
        </ScrollView>
      ) : (
        body
      )}
    </SafeAreaView>
  );
}

export function Title({ children }: { children: ReactNode }) {
  const t = useTheme();
  return (
    <Text accessibilityRole="header" style={{ color: t.colors.text, fontSize: t.font.title, fontWeight: '700' }}>
      {children}
    </Text>
  );
}

export function Heading({ children }: { children: ReactNode }) {
  const t = useTheme();
  return (
    <Text accessibilityRole="header" style={{ color: t.colors.text, fontSize: t.font.heading, fontWeight: '600' }}>
      {children}
    </Text>
  );
}

export function Body({ children, muted, center }: { children: ReactNode; muted?: boolean; center?: boolean }) {
  const t = useTheme();
  return (
    <Text style={{ color: muted ? t.colors.textMuted : t.colors.text, fontSize: t.font.body, textAlign: center ? 'center' : 'auto' }}>
      {children}
    </Text>
  );
}

export function Small({ children, muted = true }: { children: ReactNode; muted?: boolean }) {
  const t = useTheme();
  return <Text style={{ color: muted ? t.colors.textMuted : t.colors.text, fontSize: t.font.small }}>{children}</Text>;
}

type ButtonProps = {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  loading?: boolean;
  disabled?: boolean;
  accessibilityHint?: string;
  compact?: boolean;
};

export function Button({ label, onPress, variant = 'primary', loading, disabled, accessibilityHint, compact }: ButtonProps) {
  const t = useTheme();
  const fill = variant === 'primary' ? t.colors.primary : 'transparent';
  const fg = variant === 'primary' ? t.colors.onPrimary : variant === 'danger' ? t.colors.danger : t.colors.primary;
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!inactive, busy: !!loading }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 44,
        paddingHorizontal: t.space(compact ? 3 : 4),
        borderRadius: t.radius.md,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: fill,
        borderWidth: variant === 'primary' ? 0 : 1,
        borderColor: variant === 'danger' ? t.colors.danger : t.colors.border,
        opacity: inactive ? 0.55 : pressed ? 0.8 : 1,
        alignSelf: compact ? 'flex-start' : 'stretch',
      })}
    >
      {loading ? <ActivityIndicator color={fg} /> : <Text style={{ color: fg, fontSize: t.font.body, fontWeight: '600' }}>{label}</Text>}
    </Pressable>
  );
}

export function Field({ label, error, ...input }: TextInputProps & { label: string; error?: string }) {
  const t = useTheme();
  return (
    <View style={{ gap: t.space(1) }}>
      <Text style={{ color: t.colors.text, fontSize: t.font.small, fontWeight: '600' }}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={t.colors.textMuted}
        style={{
          minHeight: 44,
          borderWidth: 1,
          borderColor: error ? t.colors.danger : t.colors.border,
          borderRadius: t.radius.md,
          paddingHorizontal: t.space(3),
          color: t.colors.text,
          backgroundColor: t.colors.surface,
          fontSize: t.font.body,
        }}
        {...input}
      />
      {error ? (
        <Text accessibilityLiveRegion="polite" style={{ color: t.colors.danger, fontSize: t.font.small }}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

export function Surface({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  const t = useTheme();
  return (
    <View
      style={[
        { backgroundColor: t.colors.surface, borderRadius: t.radius.lg, padding: t.space(4), gap: t.space(2), borderWidth: StyleSheet.hairlineWidth, borderColor: t.colors.border },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export function Badge({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'brand' }) {
  const t = useTheme();
  const color = { neutral: t.colors.textMuted, success: t.colors.success, warning: t.colors.warning, danger: t.colors.danger, brand: t.colors.primary }[tone];
  return (
    <View style={{ borderWidth: 1, borderColor: color, borderRadius: 999, paddingHorizontal: t.space(2), paddingVertical: 2, alignSelf: 'flex-start' }}>
      <Text style={{ color, fontSize: t.font.small, fontWeight: '600' }}>{label}</Text>
    </View>
  );
}

/** Shown on every screen whose data comes from src/adapters/demo.ts. Never hide it. */
export function DemoBanner({ waitingOn }: { waitingOn: string }) {
  const t = useTheme();
  return (
    <View
      accessibilityRole="alert"
      accessibilityLabel={`Demo data. Waiting on ${waitingOn}.`}
      style={{ backgroundColor: t.colors.demoSurface, borderRadius: t.radius.md, padding: t.space(3) }}
    >
      <Text style={{ color: t.colors.onDemo, fontWeight: '700', fontSize: t.font.small }}>DEMO DATA</Text>
      <Text style={{ color: t.colors.onDemo, fontSize: t.font.small }}>
        Not from your facility. This screen will use {waitingOn} once that API is available.
      </Text>
    </View>
  );
}

export function OfflineBanner() {
  const t = useTheme();
  return (
    <View accessibilityRole="alert" style={{ backgroundColor: t.colors.warningSurface, borderRadius: t.radius.md, padding: t.space(3) }}>
      <Text style={{ color: t.colors.warning, fontWeight: '600', fontSize: t.font.small }}>
        Offline. Showing what was saved on this phone.
      </Text>
    </View>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const t = useTheme();
  return (
    <View accessibilityRole="alert" style={{ borderColor: t.colors.danger, borderWidth: 1, borderRadius: t.radius.md, padding: t.space(3) }}>
      <Text style={{ color: t.colors.danger, fontSize: t.font.small }}>{messageFor(error)}</Text>
    </View>
  );
}

export function Row({ title, subtitle, onPress, right }: { title: string; subtitle?: string; onPress?: () => void; right?: ReactNode }) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={subtitle ? `${title}, ${subtitle}` : title}
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => ({
        minHeight: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: t.space(3),
        paddingVertical: t.space(2),
        opacity: pressed ? 0.7 : 1,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: t.colors.border,
      })}
    >
      <View style={{ flex: 1 }}>
        <Text style={{ color: t.colors.text, fontSize: t.font.body, fontWeight: '500' }}>{title}</Text>
        {subtitle ? <Text style={{ color: t.colors.textMuted, fontSize: t.font.small }}>{subtitle}</Text> : null}
      </View>
      {right ?? (onPress ? <Text style={{ color: t.colors.textMuted, fontSize: 20 }}>›</Text> : null)}
    </Pressable>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <View style={{ paddingVertical: 24 }}>
      <Body muted center>
        {text}
      </Body>
    </View>
  );
}

export function Loading() {
  const t = useTheme();
  return <ActivityIndicator accessibilityLabel="Loading" color={t.colors.primary} style={{ paddingVertical: 24 }} />;
}
