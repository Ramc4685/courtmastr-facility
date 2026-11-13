import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { portal } from '../adapters';
import { useTheme } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { Body, Button, DemoBanner, ErrorBox, Field, Heading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

/** APP-10: a message and an optional 1-5 rating to the staff inbox, for the acting-for client. */
export default function Feedback() {
  const t = useTheme();
  const { actingFor } = useHousehold();
  const [message, setMessage] = useState('');
  const [rating, setRating] = useState<number | null>(null);
  const send = useMutation({
    mutationFn: () => portal.sendFeedback({ clientId: actingFor!.client.id, message: message.trim(), rating }),
    onSuccess: () => {
      setMessage('');
      setRating(null);
    },
  });

  return (
    <Screen>
      {portal.isDemo && <DemoBanner waitingOn="feedback (POST /portal/feedback)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>From {clientName(actingFor)}</Heading>}
      <Surface>
        <Field label="Your feedback" value={message} onChangeText={(v) => { setMessage(v); send.reset(); }} multiline />
        <Small>Rating (optional)</Small>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.space(2) }}>
          {[1, 2, 3, 4, 5].map((n) => (
            <Button key={n} compact variant={rating === n ? 'primary' : 'secondary'} label={`${n} of 5`} onPress={() => setRating(rating === n ? null : n)} />
          ))}
        </View>
        <Button label="Send feedback" onPress={() => send.mutate()} loading={send.isPending} disabled={!message.trim() || !actingFor} />
      </Surface>
      {send.error ? <ErrorBox error={send.error} /> : null}
      {send.isSuccess && <Body>Thanks, the team has your feedback.</Body>}
    </Screen>
  );
}
