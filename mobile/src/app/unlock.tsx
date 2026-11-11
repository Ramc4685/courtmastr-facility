import { useEffect, useState } from 'react';

import { useApp } from '../lib/app-state';
import { unlockWithBiometrics } from '../lib/biometric';
import { Body, Button, Screen, Title } from '../ui/kit';
import { CardPager } from '../ui/CardPager';

/** The stored session stays locked until biometrics pass. The card stays reachable without unlocking:
 * it needs no live session (ADR 0006 section 4), and a locked phone at the door must still get you in. */
export default function Unlock() {
  const { tenant, unlocked, signOut } = useApp();
  const [showCard, setShowCard] = useState(false);
  const [failed, setFailed] = useState(false);

  const attempt = async () => {
    setFailed(false);
    if (await unlockWithBiometrics()) unlocked();
    else setFailed(true);
  };

  useEffect(() => {
    // Prompt once on arrival; the button retries.
    void unlockWithBiometrics().then((ok) => (ok ? unlocked() : setFailed(true)));
  }, [unlocked]);

  return (
    <Screen>
      <Title>{tenant?.name ?? 'Locked'}</Title>
      <Body muted>Unlock to see bookings, billing and messages.</Body>
      {failed ? <Body>That did not work. Try again or sign out.</Body> : null}
      <Button label="Unlock" onPress={attempt} />
      <Button label={showCard ? 'Hide my card' : 'Show my card'} variant="secondary" onPress={() => setShowCard((v) => !v)} />
      {showCard ? <CardPager /> : null}
      <Button label="Sign out" variant="danger" onPress={() => void signOut()} />
    </Screen>
  );
}
