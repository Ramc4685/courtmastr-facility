import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import type { AppCard } from '../adapters/types';
import { useTheme } from '../lib/app-state';
import { cardCode, cardStatus, isCardSeed, type CardDisplay } from '../lib/card';
import { Barcode } from './Barcode';
import { Badge } from './kit';

/** The code on screen; a seed's code rotates every 30 s, so re-derive well inside each step. */
function useCardCode(payload: string | undefined): string | null {
  const [code, setCode] = useState<{ payload: string; text: string } | null>(null);
  useEffect(() => {
    if (!payload) return;
    let live = true;
    const tick = () => void cardCode(payload, Date.now()).then((text) => live && setCode({ payload, text }));
    tick();
    const id = isCardSeed(payload) ? setInterval(tick, 5_000) : undefined;
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [payload]);
  return code && code.payload === payload ? code.text : null;
}

type Props = { display: CardDisplay; token: AppCard | undefined; tenantName: string; now: number; online: boolean; demo: boolean; width: number };

/**
 * Always renders (A1, A3): a valid token shows the signed QR; an expired or missing token shows
 * "refresh needed" with the member number as text and a static Code 128 so the front desk can still look
 * the member up (ADR 0006 section 4). Codes sit on white with dark modules in both themes for scanners.
 */
export function MemberCard({ display, token, tenantName, now, online, demo, width }: Props) {
  const t = useTheme();
  const status = cardStatus(token, now);
  const usable = status === 'valid' || status === 'expiring';
  const until = token?.expires_at ? new Date(token.expires_at).toLocaleString() : null;
  const code = useCardCode(usable ? token?.card_payload : undefined);
  return (
    <View
      accessible
      accessibilityLabel={`Membership card for ${display.name}. ${usable ? 'Ready to scan.' : 'Refresh needed.'}`}
      style={{ width, backgroundColor: t.colors.surface, borderRadius: t.radius.lg, borderWidth: 1, borderColor: t.colors.border, overflow: 'hidden' }}
    >
      <View style={{ backgroundColor: t.colors.primary, padding: t.space(4), gap: 2 }}>
        <Text style={{ color: t.colors.onPrimary, fontSize: t.font.small, fontWeight: '600' }}>{tenantName}</Text>
        <Text style={{ color: t.colors.onPrimary, fontSize: t.font.title, fontWeight: '700' }}>{display.name}</Text>
        <Text style={{ color: t.colors.onPrimary, fontSize: t.font.small }}>{display.label}</Text>
      </View>
      <View style={{ padding: t.space(4), gap: t.space(3), alignItems: 'center' }}>
        <View style={{ flexDirection: 'row', gap: t.space(2), flexWrap: 'wrap', alignSelf: 'stretch' }}>
          {status === 'valid' && <Badge label="Ready to scan" tone="success" />}
          {status === 'expiring' && <Badge label={online ? 'Refreshing soon' : 'Refresh when online'} tone="warning" />}
          {!usable && <Badge label="Refresh needed" tone="danger" />}
          {!online && <Badge label="Offline" tone="neutral" />}
          {demo && <Badge label="Demo credential" tone="brand" />}
        </View>
        <View style={{ backgroundColor: '#FFFFFF', padding: t.space(3), borderRadius: t.radius.md, alignSelf: 'stretch', alignItems: 'center' }}>
          {usable && code ? (
            <QRCode value={code} size={Math.min(width - 80, 240)} color="#000000" backgroundColor="#FFFFFF" />
          ) : display.memberNumber ? (
            <Barcode value={display.memberNumber} />
          ) : (
            <Text style={{ color: '#111827' }}>No member number on file. Ask the front desk.</Text>
          )}
        </View>
        <Text selectable style={{ color: t.colors.text, fontSize: t.font.heading, fontWeight: '600', letterSpacing: 1 }}>
          {display.memberNumber ?? '—'}
        </Text>
        <Text style={{ color: t.colors.textMuted, fontSize: t.font.small, textAlign: 'center' }}>
          {usable
            ? `${until ? `Valid until ${until}.` : 'The code changes every 30 seconds.'} Staff confirm your photo at check-in.`
            : 'This code has expired. It refreshes next time you are online; meanwhile the desk can scan your member number.'}
        </Text>
        {demo && (
          <Text style={{ color: t.colors.onDemo, backgroundColor: t.colors.demoSurface, padding: t.space(2), borderRadius: t.radius.sm, fontSize: t.font.small, textAlign: 'center' }}>
            Demo credential generated on this phone. It will not check you in.
          </Text>
        )}
      </View>
    </View>
  );
}
