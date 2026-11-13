import { useState } from 'react';

import { portal } from '../adapters';
import { useHomeLocation, useLocations } from '../lib/hooks';
import { Body, Button, Field, Heading, Screen, Small, Surface } from '../ui/kit';
import { LocationPicker } from '../ui/LocationPicker';

export const THANKS = 'Thanks! If we can offer a trial at this location, the team will be in touch soon.';
const EMPTY = { name: '', email: '', phone: '', interest: '', message: '' };

/** APP-12 "Try us": public. The answer is always the same message, whatever the outcome (the server does the
 * same), so the form reveals nothing about which addresses or locations exist. */
export default function TryUs() {
  const locations = useLocations();
  const home = useHomeLocation();
  const [picked, setPicked] = useState<string>();
  const locationId = picked ?? home?.id;
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const set = (key: keyof typeof EMPTY) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function submit() {
    setBusy(true);
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
    } catch {
      // Same message on purpose.
    } finally {
      setBusy(false);
      setDone(true);
      setForm(EMPTY);
    }
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
        <Button label="Send request" onPress={() => void submit()} loading={busy} disabled={!form.name.trim() || !form.email.trim() || !locationId} />
      </Surface>
      <Small>We use these details only to arrange your trial.</Small>
    </Screen>
  );
}
