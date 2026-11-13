import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Image, View } from 'react-native';

import { ApiError } from '../api/errors';
import { useApp } from '../lib/app-state';
import { extractLinkToken } from '../lib/auth';
import { biometricAvailable, setBiometricEnabled } from '../lib/biometric';
import { Body, Button, ErrorBox, Field, Heading, Screen, Small, Surface, Title } from '../ui/kit';

async function offerBiometrics() {
  if (!(await biometricAvailable())) return;
  Alert.alert('Unlock with Face ID or Touch ID?', 'Keep your sign-in on this phone and unlock it with biometrics.', [
    { text: 'Not now', style: 'cancel' },
    { text: 'Turn on', onPress: () => void setBiometricEnabled(true) },
  ]);
}

export default function SignIn() {
  const { tenant, theme, signIn, requestMagicLink, consumeMagicLink } = useApp();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState<'password' | 'request' | 'consume' | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function run(kind: NonNullable<typeof busy>, action: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const onPassword = () =>
    run('password', async () => {
      await signIn(email, password);
      setPassword('');
      router.replace('/');
      void offerBiometrics();
    });

  const onRequest = () =>
    run('request', async () => {
      await requestMagicLink(email);
      setSentTo(email.trim());
    });

  const onConsume = () =>
    run('consume', async () => {
      const token = extractLinkToken(link);
      setLink('');
      if (!token) throw new ApiError({ status: 422, code: 'bad-link', detail: 'Paste the whole sign-in link from your email.' });
      await consumeMagicLink(token);
      router.replace('/');
      void offerBiometrics();
    });

  return (
    <Screen>
      <View style={{ alignItems: 'center', gap: theme.space(2), paddingVertical: theme.space(2) }}>
        {theme.brand.logoUrl ? <Image source={{ uri: theme.brand.logoUrl }} style={{ width: 72, height: 72 }} accessibilityIgnoresInvertColors /> : null}
        <Title>{tenant?.name ?? theme.brand.appName}</Title>
        {tenant?.city ? <Body muted>{tenant.city}</Body> : null}
      </View>
      <Surface>
        <Heading>Sign in</Heading>
        <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" autoCorrect={false} autoComplete="email" keyboardType="email-address" textContentType="username" />
        <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry autoComplete="password" textContentType="password" onSubmitEditing={onPassword} />
        <Button label="Sign in" onPress={onPassword} loading={busy === 'password'} disabled={!email || !password} />
        <Button label="Email me a sign-in link" variant="secondary" onPress={onRequest} loading={busy === 'request'} disabled={!email} />
        {sentTo ? <Small muted={false}>If {sentTo} has an account, a sign-in link is on its way. It works for 15 minutes.</Small> : null}
      </Surface>
      {error ? <ErrorBox error={error} /> : null}
      <Surface>
        <Heading>Opened the link on another device?</Heading>
        <Small>Tapping the link on this phone signs you in automatically. Otherwise paste it here; it is used once and never stored.</Small>
        <Field label="Sign-in link" value={link} onChangeText={setLink} autoCapitalize="none" autoCorrect={false} placeholder="https://…#token=…" />
        <Button label="Use link" variant="secondary" onPress={onConsume} loading={busy === 'consume'} disabled={!link} />
      </Surface>
      <Button label="New here? Request a free trial" variant="secondary" onPress={() => router.push('/try-us')} />
      <Button label="Contacts" variant="secondary" onPress={() => router.push('/contacts')} />
      <Button label="Choose a different facility" variant="secondary" onPress={() => router.push('/facilities')} />
    </Screen>
  );
}
