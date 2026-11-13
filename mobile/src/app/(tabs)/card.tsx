import { router } from 'expo-router';

import { useApp } from '../../lib/app-state';
import { useAppConfig } from '../../lib/hooks';
import { Body, Button, Screen } from '../../ui/kit';
import { CardPager } from '../../ui/CardPager';

export default function CardTab() {
  const { theme } = useApp();
  const walletOn = useAppConfig().data?.features.wallet_pass ?? true;
  return (
    <Screen>
      <Body muted>Show this at the front desk or kiosk. It works without a connection.</Body>
      <CardPager />
      <Body muted>Cards for everyone in your household are on every guardian&apos;s phone. Brightness up helps scanners. ({theme.brand.appName})</Body>
      {walletOn && <Button variant="secondary" label="Wallet pass" onPress={() => router.push('/wallet')} />}
    </Screen>
  );
}
