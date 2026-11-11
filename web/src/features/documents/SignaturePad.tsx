import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/Button'

/** Draw-to-sign canvas (pointer events: mouse, pen, touch). Ink is black on white so the PDF copy reads the same in
 * any theme. People who cannot draw sign by typing their name instead; the parent always offers that. */
export function SignaturePad({ label, onChange }: { label: string; onChange: (png: string | null) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const [empty, setEmpty] = useState(true)

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height)
    ctx.lineWidth = 2.5
    ctx.lineCap = 'round'
    ctx.strokeStyle = '#111111'
  }, [])

  const point = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const scale = e.currentTarget.width / rect.width
    return [(e.clientX - rect.left) * scale, (e.clientY - rect.top) * scale] as const
  }
  const clear = () => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height)
    setEmpty(true)
    onChange(null)
  }
  return (
    <div className="space-y-2">
      <canvas
        ref={canvas}
        width={600}
        height={180}
        role="img"
        aria-label={`${label}: drawing area${empty ? ', empty' : ', signed'}`}
        className="w-full touch-none rounded border border-border"
        onPointerDown={(e) => {
          drawing.current = true
          e.currentTarget.setPointerCapture(e.pointerId)
          const ctx = e.currentTarget.getContext('2d')
          const [x, y] = point(e)
          ctx?.beginPath()
          ctx?.moveTo(x, y)
        }}
        onPointerMove={(e) => {
          if (!drawing.current) return
          const ctx = e.currentTarget.getContext('2d')
          const [x, y] = point(e)
          ctx?.lineTo(x, y)
          ctx?.stroke()
        }}
        onPointerUp={(e) => {
          if (!drawing.current) return
          drawing.current = false
          setEmpty(false)
          onChange(e.currentTarget.toDataURL('image/png'))
        }}
      />
      <Button size="sm" variant="secondary" onClick={clear} disabled={empty}>
        Clear signature
      </Button>
    </div>
  )
}
