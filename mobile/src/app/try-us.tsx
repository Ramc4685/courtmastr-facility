import { useState } from 'react';
import { View } from 'react-native';

import { portal } from '../adapters';
import { ApiError } from '../api/errors';
import { useHomeLocation, useLocations } from '../lib/hooks';
import { Body, Button, Field, Heading, Screen, Small, Surface } from '../ui/kit';
import { LocationPicker } from '../ui/LocationPicker';

export const THANKS = 'Thanks! If we can offer a trial at this location, the team will be in touch soon.';
export const NOT_SENT = "Couldn't send your request. Check your connection and try again.";
const EMPTY = { name: '', email: '', phone: '', interest: '', message: '' };

/** APP-12 "Try us": public. Every answer the server gives (stored, refused, rate limited) shows the same
 * message, as the server intends, so the form reveals nothing about which addresses or locations exist. Only
 * no answer at all (offline) or a server failure (5xx) says the request was not sent, keeping what was typed. */
export default function TryUs() {
  const locations = useLocations();
  const home = useHomeLocation();
  const [picked, setPicked] = useState<string>();
  const locationId = picked ?? home?.id;
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [notSent, setNotSent] = useState(false);
  const set = (key: keyof typeof EMPTY) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function submit() {
    setBusy(true);
    setNotSent(false);
    const blank = (v: string) => v.trim() || null;
    try {
      await portal.requestTrial({
        name: form.name.trim(),
        email: form.email.trim(),
        phone: blank(form.phone),
        interest: blank(form.interest),
        message: blank(form.message),
        location_id: locationId!,
      });
    } catch (e) {
      if (!(e instanceof ApiError) || e.isNetwork || e.status >= 500) {
        setBusy(false);
        setNotSent(true);
        return;
      }
      // Any other server answer: the same message on purpose.
    }
    setBusy(false);
    setDone(true);
    setForm(EMPTY);
  }

  if (done)
    return (
      <Screen>
        <Surface>
          <Body>{THANKS}</Body>
        </Surface>
        <Button label="Send another request" variant="secondary" onPress={() => setDone(false)} />
      </Screen>
    );

  return (
    <Screen>
      <Heading>Request a free trial</Heading>
      <LocationPicker locations={locations.data ?? []} value={locationId} onChange={setPicked} />
      <Surface>
        <Field label="Name" value={form.name} onChangeText={set('name')} autoComplete="name" textContentType="name" />
        <Field label="Email" value={form.email} onChangeText={set('email')} autoCapitalize="none" autoCorrect={false} autoComplete="email" keyboardType="email-address" textContentType="emailAddress" />
        <Field label="Phone (optional)" value={form.phone} onChangeText={set('phone')} autoComplete="tel" keyboardType="phone-pad" textContentType="telephoneNumber" />
        <Field label="What would you like to try? (optional)" value={form.interest} onChangeText={set('interest')} />
        <Field label="Message (optional)" value={form.message} onChangeText={set('message')} multiline />
        {notSent ? (
          <View accessibilityRole="alert">
            <Body>{NOT_SENT}</Body>
          </View>
        ) : null}
        <Button label="Send request" onPress={() => void submit()} loading={busy} disabled={!form.name.trim() || !form.email.trim() || !locationId} />
      </Surface>
      <Small>We use these details only to arrange your trial.</Small>
    </Screen>
  );
}
