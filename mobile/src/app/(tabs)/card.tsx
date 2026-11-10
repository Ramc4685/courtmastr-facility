import { useApp } from '../../lib/app-state';
import { Body, Screen } from '../../ui/kit';
import { CardPager } from '../../ui/CardPager';

export default function CardTab() {
  const { theme } = useApp();
  return (
    <Screen>
      <Body muted>Show this at the front desk or kiosk. It works without a connection.</Body>
      <CardPager />
      <Body muted>Cards for everyone in your household are on every guardian&apos;s phone. Brightness up helps scanners. ({theme.brand.appName})</Body>
    </Screen>
  );
}
