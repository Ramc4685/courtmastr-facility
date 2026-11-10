import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Toast = { id: number; tone: 'success' | 'error'; message: string }
const ToastContext = createContext<(tone: Toast['tone'], message: string) => void>(() => {})

let next = 1

/** Toasts announce through one polite live region that is always mounted, so screen readers hear them. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const show = useCallback(
    (tone: Toast['tone'], message: string) => {
      const id = next++
      setToasts((all) => [...all, { id, tone, message }])
      window.setTimeout(() => dismiss(id), tone === 'error' ? 8000 : 5000)
    },
    [dismiss],
  )
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100%-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-3 rounded-lg border bg-surface p-3 shadow-lg ${t.tone === 'error' ? 'border-danger/40' : 'border-success/40'}`}
          >
            <span aria-hidden="true" className={`mt-1 h-2 w-2 shrink-0 rounded-full ${t.tone === 'error' ? 'bg-danger' : 'bg-success'}`} />
            <p className="flex-1">
              <span className="sr-only">{t.tone === 'error' ? 'Error: ' : ''}</span>
              {t.message}
            </p>
            <button type="button" onClick={() => dismiss(t.id)} className="text-muted hover:text-fg" aria-label="Dismiss notification">
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
