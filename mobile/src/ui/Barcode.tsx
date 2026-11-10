import JsBarcode from 'jsbarcode';
import Svg, { Rect } from 'react-native-svg';

/** Code 128 bit pattern ('1' = bar) for a value; JsBarcode renders into a plain object target. */
export function code128Bits(value: string): string {
  const target: { encodings?: { data: string }[] } = {};
  JsBarcode(target, value, { format: 'CODE128' });
  return (target.encodings ?? []).map((e) => e.data).join('');
}

export function Barcode({ value, height = 72, color = '#000000' }: { value: string; height?: number; color?: string }) {
  const bits = code128Bits(value);
  return (
    <Svg width="100%" height={height} viewBox={`0 0 ${bits.length} ${height}`} preserveAspectRatio="none" accessibilityLabel={`Barcode for ${value}`}>
      {[...bits].map((bit, i) => (bit === '1' ? <Rect key={i} x={i} y={0} width={1} height={height} fill={color} /> : null))}
    </Svg>
  );
}
