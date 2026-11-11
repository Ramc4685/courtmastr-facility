import { useEffect, useRef } from 'react'

/** Keyboard-wedge barcode and RFID readers "type" a value very fast and finish with Enter. A burst is at least
 * `minLength` characters with every gap under `maxGapMs`; slower typing is a person and is left alone. */
export type ScanOptions = { minLength?: number; maxGapMs?: number }

export function createScanBuffer({ minLength = 4, maxGapMs = 40 }: ScanOptions = {}) {
  let chars = ''
  let last = 0
  return {
    /** Feed one key; returns the scanned value when this Enter ends a burst, else null. */
    push(key: string, at: number): string | null {
      if (at - last > maxGapMs) chars = ''
      last = at
      if (key === 'Enter') {
        const value = chars
        chars = ''
        return value.length >= minLength ? value : null
      }
      if (key.length === 1) chars += key
      return null
    },
  }
}

/** Shared by the front-desk window and the kiosk (CHK-14): calls `onScan` with each scanned value, from anywhere
 * on the page, and stops the scanner's Enter from submitting whatever form has focus. */
export function useScanBurst(onScan: (value: string) => void, options?: ScanOptions) {
  const handler = useRef(onScan)
  handler.current = onScan
  const { minLength, maxGapMs } = options ?? {}
  useEffect(() => {
    const buffer = createScanBuffer({ minLength, maxGapMs })
    const listen = (event: KeyboardEvent) => {
      const value = buffer.push(event.key, event.timeStamp)
      if (value === null) return
      event.preventDefault()
      const target = event.target as HTMLElement | null
      // The burst's characters already landed in a focused text field: take them back out.
      if (target instanceof HTMLInputElement && target.value.endsWith(value)) target.value = target.value.slice(0, -value.length)
      handler.current(value)
    }
    document.addEventListener('keydown', listen, true)
    return () => document.removeEventListener('keydown', listen, true)
  }, [minLength, maxGapMs])
}
